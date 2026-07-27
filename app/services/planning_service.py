"""Composite trip planning.

Collapses the multi-step planning pipeline (destination context → place search →
route optimisation → schedule) into a single server-side call. The agent invokes
one ``plan_trip`` tool instead of chaining 5+ tool round-trips, which sharply cuts
latency and token cost.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field

from app.config import Settings
from app.enums import Mood, Region, StopType, TravellerType, TripDuration
from app.locations import get_location_provider
from app.services import providers
from app.services.catalog import Place
from app.services.maps_service import Coordinate, RouteStopInput

# Default minutes spent at each kind of stop.
_DWELL = {
    StopType.ATTRACTION: 60,
    StopType.SCENIC_LOOKOUT: 45,
    StopType.CAFE: 45,
    StopType.RESTAURANT: 75,
    StopType.REST_STOP: 20,
}

# Target number of stops per trip duration.
_TARGET_STOPS = {
    TripDuration.ONE_HOUR: 3,
    TripDuration.HALF_DAY: 4,
    TripDuration.FULL_DAY: 6,
    TripDuration.WEEKEND: 7,
    TripDuration.MULTI_DAY: 8,
}


class PlannedStop(BaseModel):
    order: int
    place_name: str
    stop_type: StopType
    latitude: float
    longitude: float
    rating: float | None = None
    opening_hours: str | None = None
    description: str | None = None
    dwell_minutes: int
    distance_from_prev_km: float
    drive_minutes_from_prev: int
    arrival_time: datetime
    departure_time: datetime


class PlannedItinerary(BaseModel):
    title: str
    region: Region
    origin: str
    destination: str
    traveller_type: TravellerType
    duration: TripDuration
    moods: list[str] = Field(default_factory=list)
    context_summary: str | None = None
    context_source_url: str | None = None
    stops: list[PlannedStop]
    total_distance_km: float
    total_drive_minutes: int
    recommended_rest_breaks: int
    notes: list[str] = Field(default_factory=list)


def _select_places(
    attractions: list[Place], dining: list[Place], *, target: int, want_cafe: bool
) -> list[Place]:
    """Pick a balanced set: attractions plus at least one café and one eatery."""
    chosen: list[Place] = []
    seen: set[str] = set()

    def add(p: Place) -> None:
        if p.name not in seen:
            chosen.append(p)
            seen.add(p.name)

    cafes = [p for p in dining if p.stop_type is StopType.CAFE]
    restaurants = [p for p in dining if p.stop_type is StopType.RESTAURANT]

    # Reserve slots for dining so a trip is never all sightseeing.
    if want_cafe and cafes:
        add(cafes[0])
    if restaurants:
        add(restaurants[0])
    elif cafes and not chosen:
        add(cafes[0])

    for p in attractions:
        if len(chosen) >= target:
            break
        add(p)

    return chosen[:target]


async def plan_trip(
    settings: Settings,
    *,
    region: Region,
    origin: str,
    destination: str,
    moods: list[str],
    traveller_type: TravellerType,
    duration: TripDuration,
    depart_at: datetime | None = None,
    max_stops: int | None = None,
) -> PlannedItinerary:
    """Build a complete, optimally-ordered, time-scheduled draft itinerary."""
    moods = [m.strip().lower() for m in moods if m.strip()]
    target = max_stops or _TARGET_STOPS.get(duration, 6)
    target = max(3, min(target, 8))
    depart_at = depart_at or datetime.now(timezone.utc).replace(
        hour=9, minute=0, second=0, microsecond=0
    )

    origin_coord = await providers.geocode_place(settings, origin, region)
    near = origin_coord or await providers.geocode_place(settings, destination, region)

    attractions = await providers.find_attractions(
        settings, region=region, destination=destination,
        traveller_type=traveller_type, moods=moods, near=near, limit=target * 2,
    )
    want_cafe = Mood.COFFEE.value in moods or Mood.FOOD.value in moods or True
    dining = await providers.find_restaurants(
        settings, region=region, destination=destination,
        traveller_type=traveller_type, moods=moods, near=near, cafes_only=False, limit=6,
    )

    selected = _select_places(attractions, dining, target=target, want_cafe=want_cafe)
    by_name = {p.name: p for p in selected}

    route = await providers.plan_route(
        settings,
        stops=[
            RouteStopInput(name=p.name, latitude=p.latitude, longitude=p.longitude)
            for p in selected
        ],
        origin=origin_coord,
        scenic=True,
    )

    # Schedule: arrival = depart + cumulative(drive + prior dwell).
    stops: list[PlannedStop] = []
    clock = depart_at
    for od in route.ordered:
        place = by_name[od.name]
        clock = clock + timedelta(minutes=od.drive_minutes_from_prev)
        arrival = clock
        dwell = _DWELL.get(place.stop_type, 45)
        departure = arrival + timedelta(minutes=dwell)
        clock = departure
        stops.append(
            PlannedStop(
                order=od.order,
                place_name=place.name,
                stop_type=place.stop_type,
                latitude=place.latitude,
                longitude=place.longitude,
                rating=place.rating,
                opening_hours=place.opening_hours,
                description=place.description,
                dwell_minutes=dwell,
                distance_from_prev_km=od.distance_from_prev_km,
                drive_minutes_from_prev=od.drive_minutes_from_prev,
                arrival_time=arrival,
                departure_time=departure,
            )
        )

    notes: list[str] = []
    if route.recommended_rest_breaks:
        notes.append(
            f"Plan for ~{route.recommended_rest_breaks} rest break(s) "
            "(roughly every two hours of driving)."
        )
    if traveller_type is TravellerType.FAMILY:
        notes.append("Family trip: prioritised family-friendly stops.")

    context = None
    source_url = None
    if settings.enable_external_context:
        try:
            ctx = await get_location_provider(region).get_context(destination)
            context = ctx.summary
            source_url = ctx.source_url
        except Exception:  # context is best-effort enrichment only
            pass

    title = f"{destination} {duration.value.replace('_', ' ')} — {', '.join(moods) or 'highlights'}"
    return PlannedItinerary(
        title=title[:120],
        region=region,
        origin=origin,
        destination=destination,
        traveller_type=traveller_type,
        duration=duration,
        moods=moods,
        context_summary=context,
        context_source_url=source_url,
        stops=stops,
        total_distance_km=route.total_distance_km,
        total_drive_minutes=route.total_drive_minutes,
        recommended_rest_breaks=route.recommended_rest_breaks,
        notes=notes,
    )
