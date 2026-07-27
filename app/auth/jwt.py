"""JWT issuing and validation.

The agent must never be publicly accessible: every request carries a Helpsonroad
user's bearer token. Tokens embed the user id (``sub``), optional vehicle id,
subscription tier, and roles per the PRD.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from pydantic import BaseModel, Field

from app.config import Settings, get_settings


class Principal(BaseModel):
    """Authenticated caller extracted from a validated JWT."""

    user_id: str
    email: str | None = None
    name: str | None = None
    vehicle_id: str | None = None
    subscription_tier: str = "free"
    roles: list[str] = Field(default_factory=list)


class AuthError(Exception):
    """Raised when a token is missing, malformed, or invalid."""


def create_access_token(
    *,
    user_id: str,
    email: str | None = None,
    name: str | None = None,
    vehicle_id: str | None = None,
    subscription_tier: str = "free",
    roles: list[str] | None = None,
    expires_in: timedelta = timedelta(hours=12),
    settings: Settings | None = None,
) -> str:
    """Issue a signed access token. Used by the login flow and in tests."""
    settings = settings or get_settings()
    now = datetime.now(timezone.utc)
    claims: dict = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_in).timestamp()),
        "subscription_tier": subscription_tier,
        "roles": roles or [],
    }
    if email is not None:
        claims["email"] = email
    if name is not None:
        claims["name"] = name
    if vehicle_id is not None:
        claims["vehicle_id"] = vehicle_id
    if settings.jwt_issuer:
        claims["iss"] = settings.jwt_issuer
    if settings.jwt_audience:
        claims["aud"] = settings.jwt_audience
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str, settings: Settings | None = None) -> Principal:
    """Validate a bearer token and return the caller principal.

    Raises :class:`AuthError` on any validation failure.
    """
    settings = settings or get_settings()
    options = {"require": ["exp", "sub"]}
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options=options,
        )
    except jwt.PyJWTError as exc:  # pragma: no cover - message varies by cause
        raise AuthError(str(exc)) from exc

    sub = claims.get("sub")
    if not sub:
        raise AuthError("token missing subject")

    return Principal(
        user_id=str(sub),
        email=claims.get("email"),
        name=claims.get("name"),
        vehicle_id=claims.get("vehicle_id"),
        subscription_tier=claims.get("subscription_tier", "free"),
        roles=list(claims.get("roles", []) or []),
    )
