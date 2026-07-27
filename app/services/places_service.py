"""Places service — attractions, scenic lookouts, and rest stops."""

from __future__ import annotations

from app.enums import Region, StopType, TravellerType
from app.services.catalog import Place, load_catalog
from app.services.maps_service import Coordinate, haversine_km

ATTRACTION_TYPES = {StopType.ATTRACTION, StopType.SCENIC_LOOKOUT, StopType.REST_STOP}


def score_place(
    place: Place,
    *,
    destination: str | None,
    traveller_type: TravellerType | None,
    moods: list[str],
    near: Coordinate | None = None,
) -> float:
    """Relevance score for ranking. Higher is better."""
    score = 0.0

    requested = {m.lower() for m in moods}
    if requested:
        overlap = requested & {m.lower() for m in place.moods}
        score += 3.0 * len(overlap)

    if traveller_type is not None:
        if traveller_type.value in place.traveller_types:
            score += 2.0
        if traveller_type is TravellerType.FAMILY and place.family_friendly:
            score += 2.0

    if destination:
        if any(tok in place.haystack() for tok in destination.lower().split()):
            score += 4.0

    if place.rating:
        score += place.rating

    if near is not None:
        dist = haversine_km(near, Coordinate(latitude=place.latitude, longitude=place.longitude))
        # Gentle proximity preference: -1 point per 50 km.
        score -= dist / 50.0

    return score


def search_attractions(
    *,
    region: Region,
    destination: str | None = None,
    traveller_type: TravellerType | None = None,
    moods: list[str] | None = None,
    near: Coordinate | None = None,
    limit: int = 8,
) -> list[Place]:
    """Return attractions/scenic lookouts/rest stops ranked for this request."""
    moods = moods or []
    catalog = load_catalog(region)
    candidates = [p for p in catalog.places if p.stop_type in ATTRACTION_TYPES]
    ranked = sorted(
        candidates,
        key=lambda p: score_place(
            p, destination=destination, traveller_type=traveller_type, moods=moods, near=near
        ),
        reverse=True,
    )
    return ranked[:limit]


def find_rest_stops(*, region: Region, near: Coordinate | None = None, limit: int = 3) -> list[Place]:
    """Return rest stops, closest first when a reference point is given."""
    catalog = load_catalog(region)
    stops = [p for p in catalog.places if p.stop_type is StopType.REST_STOP]
    if near is not None:
        stops.sort(
            key=lambda p: haversine_km(
                near, Coordinate(latitude=p.latitude, longitude=p.longitude)
            )
        )
    return stops[:limit]
