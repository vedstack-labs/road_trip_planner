"""Trip persistence: save, list, fetch, and share itineraries."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db.models import Trip, TripStop
from app.schemas.trip import (
    ShareResponse,
    StopOut,
    TripCreate,
    TripListItem,
    TripOut,
)


class TripNotFoundError(Exception):
    """Raised when a trip does not exist or is not owned by the caller."""


async def save_trip(session: AsyncSession, *, user_id: str, data: TripCreate) -> Trip:
    """Persist a new itinerary and its stops."""
    trip = Trip(
        user_id=user_id,
        title=data.title,
        region=data.region.value,
        origin=data.origin,
        destination=data.destination,
        traveller_type=data.traveller_type.value,
        mood=list(data.mood),
        duration=data.duration.value,
        summary=data.summary,
    )
    for idx, stop in enumerate(data.stops, start=1):
        trip.stops.append(
            TripStop(
                stop_order=stop.order or idx,
                place_name=stop.place_name,
                stop_type=stop.stop_type.value,
                latitude=stop.latitude,
                longitude=stop.longitude,
                description=stop.description,
                rating=stop.rating,
                dwell_minutes=stop.dwell_minutes,
                arrival_time=stop.arrival_time,
                departure_time=stop.departure_time,
            )
        )
    session.add(trip)
    await session.commit()
    return await get_trip(session, user_id=user_id, trip_id=trip.id)


async def get_trip(session: AsyncSession, *, user_id: str, trip_id: str) -> Trip:
    stmt = (
        select(Trip)
        .where(Trip.id == trip_id, Trip.user_id == user_id)
        .options(selectinload(Trip.stops))
    )
    trip = (await session.execute(stmt)).scalar_one_or_none()
    if trip is None:
        raise TripNotFoundError(trip_id)
    return trip


async def list_trips(session: AsyncSession, *, user_id: str) -> list[TripListItem]:
    stmt = (
        select(Trip, func.count(TripStop.id))
        .outerjoin(TripStop, TripStop.trip_id == Trip.id)
        .where(Trip.user_id == user_id)
        .group_by(Trip.id)
        .order_by(Trip.created_at.desc())
    )
    rows = (await session.execute(stmt)).all()
    return [
        TripListItem(
            id=trip.id,
            title=trip.title,
            region=trip.region,
            origin=trip.origin,
            destination=trip.destination,
            duration=trip.duration,
            created_at=trip.created_at,
            stop_count=count,
        )
        for trip, count in rows
    ]


async def share_trip(session: AsyncSession, *, user_id: str, trip_id: str) -> ShareResponse:
    trip = await get_trip(session, user_id=user_id, trip_id=trip_id)
    if trip.share_token is None:
        trip.share_token = uuid.uuid4().hex
        await session.commit()
    base = get_settings().share_base_url.rstrip("/")
    return ShareResponse(
        trip_id=trip.id,
        share_token=trip.share_token,
        share_url=f"{base}/{trip.share_token}",
    )


async def get_shared_trip(session: AsyncSession, *, share_token: str) -> Trip:
    stmt = (
        select(Trip)
        .where(Trip.share_token == share_token)
        .options(selectinload(Trip.stops))
    )
    trip = (await session.execute(stmt)).scalar_one_or_none()
    if trip is None:
        raise TripNotFoundError(share_token)
    return trip


def to_trip_out(trip: Trip) -> TripOut:
    """Serialise an ORM trip (with stops loaded) to the API schema."""
    return TripOut(
        id=trip.id,
        title=trip.title,
        region=trip.region,
        origin=trip.origin,
        destination=trip.destination,
        traveller_type=trip.traveller_type,
        mood=list(trip.mood or []),
        duration=trip.duration,
        summary=trip.summary,
        share_token=trip.share_token,
        created_at=trip.created_at,
        stops=[
            StopOut(
                id=s.id,
                order=s.stop_order,
                place_name=s.place_name,
                stop_type=s.stop_type,
                latitude=s.latitude,
                longitude=s.longitude,
                description=s.description,
                rating=s.rating,
                dwell_minutes=s.dwell_minutes,
                arrival_time=s.arrival_time,
                departure_time=s.departure_time,
            )
            for s in sorted(trip.stops, key=lambda x: x.stop_order)
        ],
    )
