"""Google Maps Platform client (optional, key-gated).

Wraps three Google APIs behind the same shapes the curated services already
return, so the agent tools and route logic are provider-agnostic:

* Geocoding API              → resolve free-text origins/destinations.
* Places API (New)           → real attractions, cafes, restaurants.
* Routes API (computeRoutes) → real road distance/time + waypoint optimisation.

Every method raises :class:`GoogleMapsError` on failure so the provider facade
can fall back to the offline catalog/haversine path.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.config import Settings
from app.enums import StopType
from app.services.catalog import Place
from app.services.maps_service import (
    Coordinate,
    OrderedStop,
    RouteLeg,
    RoutePlan,
    RouteStopInput,
    REST_BREAK_INTERVAL_MINUTES,
)

_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
_PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

_PLACES_FIELD_MASK = ",".join(
    [
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.rating",
        "places.types",
        "places.regularOpeningHours.weekdayDescriptions",
        "places.editorialSummary",
    ]
)
_ROUTES_FIELD_MASK = ",".join(
    [
        "routes.optimizedIntermediateWaypointIndex",
        "routes.legs.distanceMeters",
        "routes.legs.duration",
    ]
)

_CAFE_TYPES = {"cafe", "coffee_shop"}
_FOOD_TYPES = {"restaurant", "meal_takeaway", "meal_delivery", "bakery", "bar"}
_LOOKOUT_TYPES = {"scenic_point", "natural_feature"}
_ATTRACTION_TYPES = {
    "tourist_attraction", "museum", "park", "national_park", "zoo", "aquarium",
    "art_gallery", "hindu_temple", "buddhist_temple", "church", "place_of_worship",
    "historical_landmark", "amusement_park",
}


class GoogleMapsError(Exception):
    """Raised on any Google Maps API error so callers can fall back."""


def _map_stop_type(types: list[str] | None, default: StopType) -> StopType:
    s = set(types or [])
    if s & _CAFE_TYPES:
        return StopType.CAFE
    if s & _FOOD_TYPES:
        return StopType.RESTAURANT
    if s & _LOOKOUT_TYPES:
        return StopType.SCENIC_LOOKOUT
    if s & _ATTRACTION_TYPES:
        return StopType.ATTRACTION
    return default


def _parse_duration_seconds(value: str | None) -> int:
    if not value:
        return 0
    return int(round(float(value.rstrip("s")))) if value.endswith("s") else int(float(value))


@dataclass
class GoogleMapsService:
    api_key: str
    timeout: float = 8.0

    async def geocode(self, address: str, *, region_code: str | None = None) -> Coordinate | None:
        params = {"address": address, "key": self.api_key}
        if region_code:
            params["region"] = region_code.lower()
        data = await self._get(_GEOCODE_URL, params=params)
        results = data.get("results") or []
        if not results:
            return None
        loc = results[0]["geometry"]["location"]
        return Coordinate(latitude=loc["lat"], longitude=loc["lng"])

    async def search_places(
        self,
        *,
        text_query: str,
        location: Coordinate | None = None,
        radius_m: int = 60000,
        included_type: str | None = None,
        default_stop_type: StopType = StopType.ATTRACTION,
        open_now: bool = False,
        min_rating: float | None = None,
        limit: int = 8,
        region_code: str | None = None,
    ) -> list[Place]:
        body: dict = {
            "textQuery": text_query,
            "maxResultCount": max(1, min(limit, 20)),
        }
        if included_type:
            body["includedType"] = included_type
        if open_now:
            body["openNow"] = True
        if min_rating is not None:
            body["minRating"] = min_rating
        if region_code:
            body["regionCode"] = region_code.upper()
        if location is not None:
            body["locationBias"] = {
                "circle": {
                    "center": {"latitude": location.latitude, "longitude": location.longitude},
                    "radius": float(radius_m),
                }
            }
        headers = {
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": _PLACES_FIELD_MASK,
        }
        data = await self._post(_PLACES_SEARCH_URL, json=body, headers=headers)
        out: list[Place] = []
        for p in data.get("places", []):
            loc = p.get("location") or {}
            if "latitude" not in loc or "longitude" not in loc:
                continue
            hours = (p.get("regularOpeningHours") or {}).get("weekdayDescriptions") or []
            out.append(
                Place(
                    name=(p.get("displayName") or {}).get("text", "Unknown"),
                    stop_type=_map_stop_type(p.get("types"), default_stop_type),
                    area=p.get("formattedAddress", ""),
                    latitude=loc["latitude"],
                    longitude=loc["longitude"],
                    rating=p.get("rating"),
                    opening_hours="; ".join(hours) if hours else None,
                    description=(p.get("editorialSummary") or {}).get("text"),
                    keywords=list(p.get("types") or []),
                )
            )
        return out[:limit]

    async def optimise_route(
        self,
        stops: list[RouteStopInput],
        *,
        origin: Coordinate,
    ) -> RoutePlan:
        """Order stops via Google's waypoint optimisation (round trip from the
        origin), dropping the synthetic return leg to keep open-path semantics."""
        if not stops:
            return RoutePlan(
                ordered=[], legs=[], total_distance_km=0.0,
                total_drive_minutes=0, recommended_rest_breaks=0,
            )
        intermediates = [
            {"location": {"latLng": {"latitude": s.latitude, "longitude": s.longitude}}}
            for s in stops
        ]
        body = {
            "origin": {"location": {"latLng": {"latitude": origin.latitude, "longitude": origin.longitude}}},
            "destination": {"location": {"latLng": {"latitude": origin.latitude, "longitude": origin.longitude}}},
            "intermediates": intermediates,
            "optimizeWaypointOrder": True,
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE",
        }
        headers = {"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": _ROUTES_FIELD_MASK}
        data = await self._post(_ROUTES_URL, json=body, headers=headers)
        routes = data.get("routes") or []
        if not routes:
            raise GoogleMapsError("Routes API returned no routes")
        route = routes[0]
        opt_index = route.get("optimizedIntermediateWaypointIndex")
        if opt_index is None:
            opt_index = list(range(len(stops)))
        legs = route.get("legs") or []

        ordered: list[OrderedStop] = []
        out_legs: list[RouteLeg] = []
        total_km = 0.0
        total_min = 0
        prev_name = "__origin__"
        # legs[k] is the drive INTO the k-th visited point; we visit intermediates
        # first (len(stops) legs), then the dropped return leg to origin.
        for k, stop_idx in enumerate(opt_index):
            stop = stops[stop_idx]
            leg = legs[k] if k < len(legs) else {}
            dist_km = round(leg.get("distanceMeters", 0) / 1000.0, 1)
            minutes = _parse_duration_seconds(leg.get("duration")) // 60
            total_km += dist_km
            total_min += minutes
            out_legs.append(
                RouteLeg(from_name=prev_name, to_name=stop.name, distance_km=dist_km, drive_minutes=minutes)
            )
            ordered.append(
                OrderedStop(
                    order=k + 1,
                    name=stop.name,
                    latitude=stop.latitude,
                    longitude=stop.longitude,
                    distance_from_prev_km=dist_km,
                    drive_minutes_from_prev=minutes,
                )
            )
            prev_name = stop.name

        return RoutePlan(
            ordered=ordered,
            legs=out_legs,
            total_distance_km=round(total_km, 1),
            total_drive_minutes=total_min,
            recommended_rest_breaks=int(total_min // REST_BREAK_INTERVAL_MINUTES),
        )

    async def leg_estimate(self, origin: Coordinate, destination: Coordinate) -> tuple[float, int]:
        """Real road distance (km) and drive time (minutes) for a single leg."""
        body = {
            "origin": {"location": {"latLng": {"latitude": origin.latitude, "longitude": origin.longitude}}},
            "destination": {"location": {"latLng": {"latitude": destination.latitude, "longitude": destination.longitude}}},
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE",
        }
        headers = {
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": "routes.distanceMeters,routes.duration",
        }
        data = await self._post(_ROUTES_URL, json=body, headers=headers)
        routes = data.get("routes") or []
        if not routes:
            raise GoogleMapsError("Routes API returned no routes")
        r = routes[0]
        km = round(r.get("distanceMeters", 0) / 1000.0, 1)
        minutes = _parse_duration_seconds(r.get("duration")) // 60
        return km, minutes

    # --- transport helpers ---
    async def _get(self, url: str, *, params: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise GoogleMapsError(str(exc)) from exc
        return self._json(resp)

    async def _post(self, url: str, *, json: dict, headers: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=json, headers=headers)
        except httpx.HTTPError as exc:
            raise GoogleMapsError(str(exc)) from exc
        return self._json(resp)

    @staticmethod
    def _json(resp: httpx.Response) -> dict:
        if resp.status_code != 200:
            raise GoogleMapsError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        # Legacy Geocoding API reports status in the body.
        status = data.get("status")
        if status not in (None, "OK", "ZERO_RESULTS"):
            raise GoogleMapsError(f"API status {status}: {data.get('error_message', '')}")
        return data


def get_google_service(settings: Settings) -> GoogleMapsService | None:
    """Return a configured client when Google is enabled, else ``None``."""
    if not settings.google_enabled or not settings.google_maps_api_key:
        return None
    return GoogleMapsService(
        api_key=settings.google_maps_api_key,
        timeout=settings.google_timeout_seconds,
    )
