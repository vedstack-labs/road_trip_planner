"""Development helper for issuing JWTs.

In production, tokens are issued by the Helpsonroad identity service. This
endpoint exists only outside production so clients and tests can obtain a token
for the trip-planner API.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.auth.jwt import create_access_token
from app.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


class DevTokenRequest(BaseModel):
    user_id: str = "dev-user"
    # Omit email/name to let provisioning derive a unique per-user email
    # (avoids the users.email UNIQUE collision when minting several dev users).
    email: str | None = None
    name: str | None = None
    vehicle_id: str | None = None
    subscription_tier: str = "premium"
    roles: list[str] = ["driver"]


class DevTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/dev-token", response_model=DevTokenResponse)
async def dev_token(body: DevTokenRequest) -> DevTokenResponse:
    settings = get_settings()
    if settings.environment.lower() == "production":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    token = create_access_token(
        user_id=body.user_id,
        email=body.email,
        name=body.name,
        vehicle_id=body.vehicle_id,
        subscription_tier=body.subscription_tier,
        roles=body.roles,
        settings=settings,
    )
    return DevTokenResponse(access_token=token)
