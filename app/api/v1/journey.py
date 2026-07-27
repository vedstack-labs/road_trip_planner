"""Journey Mode endpoints: start, live progress, advance, resume, complete."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.auth.deps import CurrentUser, DbSession
from app.schemas.journey import JourneyOut, JourneyProgress, JourneyStartRequest
from app.services import journey_service
from app.services.journey_service import (
    JourneyNotFoundError,
    JourneyStateError,
)
from app.services.trip_service import TripNotFoundError

router = APIRouter(prefix="/journey", tags=["journey"])


def _out(journey) -> JourneyOut:
    return JourneyOut.model_validate(journey, from_attributes=True)


async def _require_journey(session, user_id: str, journey_id: str):
    try:
        return await journey_service.get_journey(
            session, user_id=user_id, journey_id=journey_id
        )
    except JourneyNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Journey not found") from None


@router.post("/start", response_model=JourneyOut, status_code=status.HTTP_201_CREATED)
async def start_journey(
    body: JourneyStartRequest, user: CurrentUser, session: DbSession
) -> JourneyOut:
    try:
        journey = await journey_service.start_journey(
            session, user_id=user.id, trip_id=body.trip_id
        )
    except TripNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trip not found") from None
    return _out(journey)


@router.get("/active", response_model=JourneyProgress)
async def active_journey(user: CurrentUser, session: DbSession) -> JourneyProgress:
    journey = await journey_service.get_active_journey(session, user_id=user.id)
    if journey is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No active journey")
    return await journey_service.progress(session, journey=journey)


@router.get("/{journey_id}", response_model=JourneyProgress)
async def journey_progress(
    journey_id: str, user: CurrentUser, session: DbSession
) -> JourneyProgress:
    journey = await _require_journey(session, user.id, journey_id)
    return await journey_service.progress(session, journey=journey)


@router.post("/{journey_id}/advance", response_model=JourneyProgress)
async def advance_journey(
    journey_id: str, user: CurrentUser, session: DbSession
) -> JourneyProgress:
    journey = await _require_journey(session, user.id, journey_id)
    try:
        journey = await journey_service.advance_stop(session, journey=journey)
    except JourneyStateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return await journey_service.progress(session, journey=journey)


@router.post("/{journey_id}/resume", response_model=JourneyOut)
async def resume_journey(
    journey_id: str, user: CurrentUser, session: DbSession
) -> JourneyOut:
    journey = await _require_journey(session, user.id, journey_id)
    try:
        journey = await journey_service.resume_journey(session, journey=journey)
    except JourneyStateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return _out(journey)


@router.post("/{journey_id}/complete", response_model=JourneyOut)
async def complete_journey(
    journey_id: str, user: CurrentUser, session: DbSession
) -> JourneyOut:
    journey = await _require_journey(session, user.id, journey_id)
    journey = await journey_service.complete_journey(session, journey=journey)
    return _out(journey)
