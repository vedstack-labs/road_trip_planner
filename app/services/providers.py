"""Provider facade: prefer Google Maps when configured, else the offline path.

Agent tools call these functions and never care which backend served the data.
Any Google failure (or empty result) degrades gracefully to the curated catalog
and haversine routing, so the service keeps working without a Google key.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

from app.config import Settings
from app.enums import Mood, Region, StopType, TravellerType
from app.services import maps_service, places_service, restaurant_service
from app.services.catalog import Place, geocode as gazetteer_geocode
from app.services.google_maps import GoogleMapsError, get_google_service
from app.services.maps_service import Coordinate, DriveEstimate, RoutePlan, RouteStopInput

logger = logging.getLogger(__name__)

_REGION_CODE = {Region.AUSTRALIA: "AU", Region.NEPAL: "NP"}

# Process-local TTL cache for geocode/places results (cuts latency + Google spend).
_CACHE: dict[str, tuple[float, object]] = {}


def _cache_get(key: str, ttl: float):
    hit = _CACHE.get(key)
    if hit is None:
        return None
    expires, value = hit
    if expires < time.monotonic():
        _CACHE.pop(key, None)
        return None
    return value


def _cache_set(key: str, value, ttl: float) -> None:
    _CACHE[key] = (time.monotonic() + ttl, value)


def clear_cache() -> None:
    _CACHE.clear()


def region_code(region: Region) -> str:
    return _REGION_CODE.get(region, "")


async def geocode_place(settings: Settings, name: str, region: Region) -> Coordinate | None:
    """Resolve free-text place to coordinates (Google first, gazetteer fallback)."""
    ttl = settings.provider_cache_ttl_seconds
    key = f"geo|{settings.google_enabled}|{region.value}|{name.strip().lower()}"
    cached = _cache_get(key, ttl)
    if cached is not None:
        return cached if isinstance(cached, Coordinate) else None
    svc = get_google_service(settings)
    coord: Coordinate | None = None
    if svc is not None:
        try:
            coord = await svc.geocode(name, region_code=region_code(region))
        except GoogleMapsError as exc:
            logger.warning("Google geocode failed (%s); using gazetteer", exc)
    if coord is None:
        hit = gazetteer_geocode(name)
        coord = Coordinate(latitude=hit[0], longitude=hit[1]) if hit else None
    if coord is not None:
        _cache_set(key, coord, ttl)
    return coord


async def find_attractions(
    settings: Settings,
    *,
    region: Region,
    destination: str,
    traveller_type: TravellerType | None,
    moods: list[str],
    near: Coordinate | None,
    limit: int,
) -> list[Place]:
    ttl = settings.provider_cache_ttl_seconds
    key = (
        f"attr|{settings.google_enabled}|{region.value}|{destination.strip().lower()}"
        f"|{','.join(sorted(m.lower() for m in moods))}|{traveller_type.value if traveller_type else ''}|{limit}"
    )
    cached = _cache_get(key, ttl)
    if cached is not None:
        return list(cached)  # type: ignore[arg-type]

    out: list[Place] | None = None
    svc = get_google_service(settings)
    if svc is not None:
        try:
            location = near or await geocode_place(settings, destination, region)
            mood_terms = " ".join(moods) if moods else "top"
            query = f"{mood_terms} attractions, scenic lookouts and points of interest near {destination}"
            results = await svc.search_places(
                text_query=query,
                location=location,
                radius_m=settings.google_places_radius_m,
                default_stop_type=StopType.ATTRACTION,
                region_code=region_code(region),
                limit=limit,
            )
            if results:
                out = results
        except GoogleMapsError as exc:
            logger.warning("Google places (attractions) failed (%s); using catalog", exc)
    if out is None:
        out = places_service.search_attractions(
            region=region, destination=destination, traveller_type=traveller_type,
            moods=moods, near=near, limit=limit,
        )
    _cache_set(key, out, ttl)
    return out


async def find_restaurants(
    settings: Settings,
    *,
    region: Region,
    destination: str,
    traveller_type: TravellerType | None,
    moods: list[str],
    near: Coordinate | None,
    cafes_only: bool,
    limit: int,
) -> list[Place]:
    ttl = settings.provider_cache_ttl_seconds
    key = (
        f"dine|{settings.google_enabled}|{region.value}|{destination.strip().lower()}"
        f"|{','.join(sorted(m.lower() for m in moods))}|{cafes_only}|{limit}"
    )
    cached = _cache_get(key, ttl)
    if cached is not None:
        return list(cached)  # type: ignore[arg-type]

    out: list[Place] | None = None
    svc = get_google_service(settings)
    if svc is not None:
        try:
            location = near or await geocode_place(settings, destination, region)
            want_cafe = cafes_only or Mood.COFFEE.value in {m.lower() for m in moods}
            included = "cafe" if want_cafe else "restaurant"
            default = StopType.CAFE if want_cafe else StopType.RESTAURANT
            query = f"highly rated {'cafes and coffee' if want_cafe else 'restaurants'} near {destination}"
            results = await svc.search_places(
                text_query=query,
                location=location,
                radius_m=settings.google_places_radius_m,
                included_type=included,
                default_stop_type=default,
                min_rating=4.0,
                region_code=region_code(region),
                limit=limit,
            )
            if results:
                out = results
        except GoogleMapsError as exc:
            logger.warning("Google places (dining) failed (%s); using catalog", exc)
    if out is None:
        out = restaurant_service.search_restaurants(
            region=region, destination=destination, traveller_type=traveller_type,
            moods=moods, near=near, cafes_only=cafes_only, limit=limit,
        )
    _cache_set(key, out, ttl)
    return out


async def plan_route(
    settings: Settings,
    *,
    stops: list[RouteStopInput],
    origin: Coordinate | None,
    scenic: bool,
) -> RoutePlan:
    svc = get_google_service(settings)
    if svc is not None and origin is not None and stops:
        try:
            return await svc.optimise_route(stops, origin=origin)
        except GoogleMapsError as exc:
            logger.warning("Google routes failed (%s); using haversine 2-opt", exc)
    return maps_service.optimise_route(stops, origin=origin, scenic=scenic)


async def leg_estimate(
    settings: Settings,
    *,
    origin: Coordinate,
    destination: Coordinate,
    depart_at: datetime,
    scenic: bool,
) -> DriveEstimate:
    from datetime import timedelta

    svc = get_google_service(settings)
    if svc is not None:
        try:
            km, minutes = await svc.leg_estimate(origin, destination)
            return DriveEstimate(distance_km=km, drive_minutes=minutes, eta=depart_at + timedelta(minutes=minutes))
        except GoogleMapsError as exc:
            logger.warning("Google leg estimate failed (%s); using haversine", exc)
    return maps_service.estimate_drive_time(origin, destination, depart_at=depart_at, scenic=scenic)
