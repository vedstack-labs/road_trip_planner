"""SQLAlchemy ORM models.

Schema mirrors the PRD (users, trips, trip_stops, journeys) with pragmatic
additions required to make the MVP function: vehicles and JSON preference/mood
columns, plus share tokens. IDs are UUID strings so the schema is portable
across PostgreSQL and SQLite (used for local/dev/tests).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.enums import JourneyStatus, StopType


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    subscription_tier: Mapped[str] = mapped_column(String(32), default="free")
    # Free-form defaults the agent uses without re-asking (home region, moods...).
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    vehicles: Mapped[list["Vehicle"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    trips: Mapped[list["Trip"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    make: Mapped[str | None] = mapped_column(String(80), default=None)
    model: Mapped[str | None] = mapped_column(String(80), default=None)
    registration: Mapped[str | None] = mapped_column(String(20), default=None)

    user: Mapped[User] = relationship(back_populates="vehicles")


class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    region: Mapped[str] = mapped_column(String(32), default="australia")
    origin: Mapped[str] = mapped_column(String(200))
    destination: Mapped[str] = mapped_column(String(200))
    traveller_type: Mapped[str] = mapped_column(String(32))
    # List of mood strings.
    mood: Mapped[list] = mapped_column(JSON, default=list)
    duration: Mapped[str] = mapped_column(String(32))
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    share_token: Mapped[str | None] = mapped_column(String(36), unique=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    user: Mapped[User] = relationship(back_populates="trips")
    stops: Mapped[list["TripStop"]] = relationship(
        back_populates="trip",
        cascade="all, delete-orphan",
        order_by="TripStop.stop_order",
    )
    journeys: Mapped[list["Journey"]] = relationship(
        back_populates="trip", cascade="all, delete-orphan"
    )


class TripStop(Base):
    __tablename__ = "trip_stops"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    # "order" is a SQL keyword; store as stop_order, expose as `order` in the API.
    stop_order: Mapped[int] = mapped_column(Integer)
    place_name: Mapped[str] = mapped_column(String(200))
    stop_type: Mapped[str] = mapped_column(String(32), default=StopType.ATTRACTION.value)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    rating: Mapped[float | None] = mapped_column(Float, default=None)
    # Minutes spent at the location.
    dwell_minutes: Mapped[int] = mapped_column(Integer, default=30)
    arrival_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    departure_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    trip: Mapped[Trip] = relationship(back_populates="stops")

    __table_args__ = (UniqueConstraint("trip_id", "stop_order", name="uq_trip_stop_order"),)


class Journey(Base):
    __tablename__ = "journeys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default=JourneyStatus.PLANNED.value)
    current_stop_index: Mapped[int] = mapped_column(Integer, default=0)
    # Populated while a roadside incident pauses the journey.
    roadside_reason: Mapped[str | None] = mapped_column(Text, default=None)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    trip: Mapped[Trip] = relationship(back_populates="journeys")


class Conversation(Base):
    """Serialized PydanticAI message history for a chat session.

    Persisting history (rather than keeping it in process memory) keeps the
    agent stateless so it scales horizontally on Kubernetes.
    """

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # PydanticAI ModelMessagesTypeAdapter JSON dump.
    messages: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
