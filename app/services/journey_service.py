"""Journey Mode: track the active trip, pause/resume around roadside events."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Journey, Trip
from app.enums import JourneyStatus, StopType
from app.schemas.journey import JourneyProgress
from app.services.maps_service import Coordinate, estimate_leg
from app.services.trip_service import TripNotFoundError

ATTRACTION_TYPES = {StopType.ATTRACTION.value, StopType.SCENIC_LOOKOUT.value}
DINING_TYPES = {StopType.CAFE.value, StopType.RESTAURANT.value}


class JourneyStateError(Exception):
    """Raised when an operation is invalid for the journey's current state."""


class JourneyNotFoundError(Exception):
    """Raised when a journey does not exist or is not owned by the caller."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _load_trip(session: AsyncSession, user_id: str, trip_id: str) -> Trip:
    stmt = (
        select(Trip)
        .where(Trip.id == trip_id, Trip.user_id == user_id)
        .options(selectinload(Trip.stops))
    )
    trip = (await session.execute(stmt)).scalar_one_or_none()
    if trip is None:
        raise TripNotFoundError(trip_id)
    return trip


async def start_journey(session: AsyncSession, *, user_id: str, trip_id: str) -> Journey:
    """Activate Journey Mode for a trip, reusing any existing session."""
    await _load_trip(session, user_id, trip_id)  # ownership + existence check

    stmt = select(Journey).where(Journey.trip_id == trip_id, Journey.user_id == user_id)
    journey = (await session.execute(stmt)).scalars().first()
    if journey is None:
        journey = Journey(user_id=user_id, trip_id=trip_id)
        session.add(journey)

    journey.status = JourneyStatus.ACTIVE.value
    journey.started_at = journey.started_at or _utcnow()
    journey.roadside_reason = None
    await session.commit()
    await session.refresh(journey)
    return journey


async def get_active_journey(session: AsyncSession, *, user_id: str) -> Journey | None:
    """Return the user's currently active or paused journey, if any."""
    stmt = (
        select(Journey)
        .where(
            Journey.user_id == user_id,
            Journey.status.in_([JourneyStatus.ACTIVE.value, JourneyStatus.PAUSED.value]),
        )
        .order_by(Journey.updated_at.desc())
    )
    return (await session.execute(stmt)).scalars().first()


async def get_journey(session: AsyncSession, *, user_id: str, journey_id: str) -> Journey:
    """Return a journey by id, enforcing ownership."""
    journey = await session.get(Journey, journey_id)
    if journey is None or journey.user_id != user_id:
        raise JourneyNotFoundError(journey_id)
    return journey


async def pause_journey(session: AsyncSession, *, journey: Journey, reason: str) -> Journey:
    journey.status = JourneyStatus.PAUSED.value
    journey.roadside_reason = reason
    await session.commit()
    await session.refresh(journey)
    return journey


async def resume_journey(session: AsyncSession, *, journey: Journey) -> Journey:
    if journey.status == JourneyStatus.COMPLETED.value:
        raise JourneyStateError("cannot resume a completed journey")
    journey.status = JourneyStatus.ACTIVE.value
    journey.roadside_reason = None
    await session.commit()
    await session.refresh(journey)
    return journey


async def complete_journey(session: AsyncSession, *, journey: Journey) -> Journey:
    journey.status = JourneyStatus.COMPLETED.value
    await session.commit()
    await session.refresh(journey)
    return journey


async def advance_stop(session: AsyncSession, *, journey: Journey) -> Journey:
    """Advance the active journey to the next stop; auto-completes past the last.

    Only valid while ACTIVE (a PAUSED roadside journey must resume first).
    """
    if journey.status != JourneyStatus.ACTIVE.value:
        raise JourneyStateError(
            f"cannot advance a journey in state {journey.status!r}; resume it first"
        )
    trip = await _load_trip(session, journey.user_id, journey.trip_id)
    last_index = max(len(trip.stops) - 1, 0)
    if journey.current_stop_index >= last_index:
        journey.status = JourneyStatus.COMPLETED.value
    else:
        journey.current_stop_index += 1
    await session.commit()
    await session.refresh(journey)
    return journey


async def progress(session: AsyncSession, *, journey: Journey) -> JourneyProgress:
    """Compute a live progress snapshot for the journey."""
    trip = await _load_trip(session, journey.user_id, journey.trip_id)
    stops = sorted(trip.stops, key=lambda s: s.stop_order)
    idx = journey.current_stop_index

    current = stops[idx].place_name if 0 <= idx < len(stops) else None

    next_attraction = next(
        (s.place_name for s in stops[idx:] if s.stop_type in ATTRACTION_TYPES), None
    )
    next_restaurant = next(
        (s.place_name for s in stops[idx:] if s.stop_type in DINING_TYPES), None
    )

    remaining = stops[idx:]
    remaining_minutes = 0
    for a, b in zip(remaining, remaining[1:]):
        _, minutes = estimate_leg(
            Coordinate(latitude=a.latitude, longitude=a.longitude),
            Coordinate(latitude=b.latitude, longitude=b.longitude),
        )
        remaining_minutes += minutes

    return JourneyProgress(
        journey_id=journey.id,
        status=JourneyStatus(journey.status),
        current_stop=current,
        next_attraction=next_attraction,
        next_restaurant=next_restaurant,
        remaining_stops=max(len(stops) - idx - 1, 0),
        remaining_drive_minutes=remaining_minutes,
    )
