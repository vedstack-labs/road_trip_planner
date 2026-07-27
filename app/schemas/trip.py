"""Trip and itinerary schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.enums import Region, StopType, TravellerType, TripDuration


class StopInput(BaseModel):
    order: int | None = Field(default=None, description="1-based driving order; assigned if omitted")
    place_name: str
    stop_type: StopType = StopType.ATTRACTION
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    description: str | None = None
    rating: float | None = Field(default=None, ge=0, le=5)
    dwell_minutes: int = Field(default=30, ge=0, le=24 * 60)
    arrival_time: datetime | None = None
    departure_time: datetime | None = None


class TripCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    region: Region = Region.AUSTRALIA
    origin: str = Field(min_length=1, max_length=200)
    destination: str = Field(min_length=1, max_length=200)
    traveller_type: TravellerType
    mood: list[str] = Field(default_factory=list)
    duration: TripDuration
    summary: str | None = None
    stops: list[StopInput] = Field(default_factory=list)

    @field_validator("stops")
    @classmethod
    def _limit_stops(cls, v: list[StopInput]) -> list[StopInput]:
        if len(v) > 20:
            raise ValueError("a trip may contain at most 20 stops")
        return v


class StopOut(BaseModel):
    id: str
    order: int
    place_name: str
    stop_type: StopType
    latitude: float
    longitude: float
    description: str | None
    rating: float | None
    dwell_minutes: int
    arrival_time: datetime | None
    departure_time: datetime | None


class TripOut(BaseModel):
    id: str
    title: str
    region: Region
    origin: str
    destination: str
    traveller_type: str
    mood: list[str]
    duration: str
    summary: str | None
    share_token: str | None
    created_at: datetime
    stops: list[StopOut]


class TripListItem(BaseModel):
    id: str
    title: str
    region: Region
    origin: str
    destination: str
    duration: str
    created_at: datetime
    stop_count: int


class ShareResponse(BaseModel):
    trip_id: str
    share_token: str
    share_url: str
