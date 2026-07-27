"""Journey mode schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.enums import JourneyStatus


class JourneyStartRequest(BaseModel):
    trip_id: str


class JourneyOut(BaseModel):
    id: str
    trip_id: str
    status: JourneyStatus
    current_stop_index: int
    roadside_reason: str | None
    started_at: datetime | None
    updated_at: datetime


class JourneyProgress(BaseModel):
    """Live view of an active journey (current stop, next stops, ETA)."""

    journey_id: str
    status: JourneyStatus
    current_stop: str | None
    next_attraction: str | None
    next_restaurant: str | None
    remaining_stops: int
    remaining_drive_minutes: int
