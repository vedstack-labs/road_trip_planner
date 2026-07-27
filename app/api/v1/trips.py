"""Trip CRUD and sharing endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.auth.deps import CurrentUser, DbSession
from app.schemas.trip import (
    ShareResponse,
    TripCreate,
    TripListItem,
    TripOut,
)
from app.services import trip_service
from app.services.trip_service import TripNotFoundError

router = APIRouter(prefix="/trips", tags=["trips"])


@router.post("", response_model=TripOut, status_code=status.HTTP_201_CREATED)
async def create_trip(body: TripCreate, user: CurrentUser, session: DbSession) -> TripOut:
    trip = await trip_service.save_trip(session, user_id=user.id, data=body)
    return trip_service.to_trip_out(trip)


@router.get("", response_model=list[TripListItem])
async def list_trips(user: CurrentUser, session: DbSession) -> list[TripListItem]:
    return await trip_service.list_trips(session, user_id=user.id)


# Public read of a shared itinerary. Declared before "/{trip_id}" so the literal
# path wins over the path parameter.
@router.get("/shared/{share_token}", response_model=TripOut, tags=["public"])
async def get_shared_trip(share_token: str, session: DbSession) -> TripOut:
    try:
        trip = await trip_service.get_shared_trip(session, share_token=share_token)
    except TripNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shared trip not found") from None
    return trip_service.to_trip_out(trip)


@router.get("/{trip_id}", response_model=TripOut)
async def get_trip(trip_id: str, user: CurrentUser, session: DbSession) -> TripOut:
    try:
        trip = await trip_service.get_trip(session, user_id=user.id, trip_id=trip_id)
    except TripNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trip not found") from None
    return trip_service.to_trip_out(trip)


@router.post("/{trip_id}/share", response_model=ShareResponse)
async def share_trip(trip_id: str, user: CurrentUser, session: DbSession) -> ShareResponse:
    try:
        return await trip_service.share_trip(session, user_id=user.id, trip_id=trip_id)
    except TripNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trip not found") from None
