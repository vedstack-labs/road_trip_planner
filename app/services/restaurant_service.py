"""Restaurant service — cafes and restaurants with ratings and opening hours."""

from __future__ import annotations

from app.enums import Mood, Region, StopType, TravellerType
from app.services.catalog import Place, load_catalog
from app.services.maps_service import Coordinate
from app.services.places_service import score_place

DINING_TYPES = {StopType.CAFE, StopType.RESTAURANT}


def search_restaurants(
    *,
    region: Region,
    destination: str | None = None,
    traveller_type: TravellerType | None = None,
    moods: list[str] | None = None,
    near: Coordinate | None = None,
    cafes_only: bool = False,
    limit: int = 5,
) -> list[Place]:
    """Return highly rated cafes/restaurants ranked for this request.

    When the request is coffee-led we bias towards cafes; ``cafes_only`` forces
    it. Results are ranked by mood/traveller/destination fit and rating, then
    ties break on the higher rating.
    """
    moods = moods or []
    catalog = load_catalog(region)

    wants_coffee = Mood.COFFEE.value in {m.lower() for m in moods}
    allowed = {StopType.CAFE} if cafes_only else DINING_TYPES
    candidates = [p for p in catalog.places if p.stop_type in allowed]

    def key(p: Place) -> tuple[float, float]:
        base = score_place(
            p, destination=destination, traveller_type=traveller_type, moods=moods, near=near
        )
        if wants_coffee and p.stop_type is StopType.CAFE:
            base += 2.0
        return (base, p.rating or 0.0)

    ranked = sorted(candidates, key=key, reverse=True)
    return ranked[:limit]
