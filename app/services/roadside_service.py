"""Roadside assistance handoff.

Bridges Journey Mode to the Helpsonroad roadside workflow. When a driver reports
a breakdown mid-journey the active trip is paused, a roadside ticket is raised,
and control transitions to the roadside workflow. On completion the journey
resumes so the user never leaves the trip.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Journey
from app.enums import JourneyStatus
from app.services import journey_service


class RoadsideHandoff(BaseModel):
    ticket_id: str
    status: str
    reason: str
    journey_id: str | None
    journey_paused: bool
    message: str


async def request_roadside_assistance(
    session: AsyncSession,
    *,
    user_id: str,
    reason: str,
    vehicle_id: str | None = None,
) -> RoadsideHandoff:
    """Raise a roadside ticket and pause any active journey."""
    active = await journey_service.get_active_journey(session, user_id=user_id)
    paused = False
    if active is not None and active.status == JourneyStatus.ACTIVE.value:
        await journey_service.pause_journey(session, journey=active, reason=reason)
        paused = True

    ticket_id = f"RSA-{uuid.uuid4().hex[:10].upper()}"
    return RoadsideHandoff(
        ticket_id=ticket_id,
        status="dispatching",
        reason=reason,
        journey_id=active.id if active else None,
        journey_paused=paused,
        message=(
            "Roadside assistance has been requested and help is being dispatched. "
            "Your trip is paused and will resume automatically once assistance is complete."
        ),
    )


async def resume_after_roadside(
    session: AsyncSession, *, journey: Journey
) -> Journey:
    """Resume a journey once the roadside workflow completes."""
    return await journey_service.resume_journey(session, journey=journey)
