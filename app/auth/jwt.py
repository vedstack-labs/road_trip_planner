"""JWT issuing and validation.

The agent must never be publicly accessible: every request carries a Helpsonroad
user's bearer token. Tokens embed the user id (``sub``), optional vehicle id,
subscription tier, and roles per the PRD.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache

import jwt
from jwt import PyJWKClient
from pydantic import BaseModel, Field

from app.config import Settings, get_settings

# Algorithms whose keys come from the JWKS endpoint rather than the shared
# secret. Supabase/Lovable Cloud signs with ES256.
_ASYMMETRIC_ALGS = frozenset({"ES256", "ES384", "ES512", "RS256", "RS384", "RS512"})


@lru_cache(maxsize=8)
def _jwks_client(url: str) -> PyJWKClient:
    """Cached JWKS client (keys are cached in-process across warm invocations)."""
    return PyJWKClient(url, cache_keys=True, lifespan=3600, max_cached_keys=16)


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

    Symmetric tokens (HS256, from the dev-token flow) are verified with the
    shared secret. Asymmetric tokens (ES256/RS256, e.g. Supabase/Lovable Cloud)
    are verified against the configured JWKS endpoint, selecting the key by the
    token's ``kid`` header. Raises :class:`AuthError` on any validation failure.
    """
    settings = settings or get_settings()
    allowed = settings.jwt_algorithm_list

    try:
        alg = jwt.get_unverified_header(token).get("alg")
    except jwt.PyJWTError as exc:
        raise AuthError(str(exc)) from exc

    # Verify the audience only when one is configured; passing audience=None
    # while the token carries an `aud` claim (Supabase uses "authenticated")
    # would otherwise raise InvalidAudienceError.
    options = {"require": ["exp", "sub"], "verify_aud": settings.jwt_audience is not None}

    try:
        if alg in _ASYMMETRIC_ALGS:
            if not settings.jwt_jwks_url:
                raise AuthError(f"no JWKS configured for asymmetric token (alg={alg})")
            key = _jwks_client(settings.jwt_jwks_url).get_signing_key_from_jwt(token).key
        else:
            key = settings.jwt_secret
        claims = jwt.decode(
            token,
            key,
            algorithms=allowed,
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options=options,
        )
    except (jwt.PyJWTError, OSError) as exc:  # OSError covers JWKS fetch failures
        raise AuthError(str(exc)) from exc

    sub = claims.get("sub")
    if not sub:
        raise AuthError("token missing subject")

    metadata = claims.get("user_metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    return Principal(
        user_id=str(sub),
        email=claims.get("email") or metadata.get("email"),
        name=claims.get("name") or metadata.get("full_name") or metadata.get("name"),
        vehicle_id=claims.get("vehicle_id"),
        subscription_tier=claims.get("subscription_tier", "free"),
        roles=list(claims.get("roles", []) or []),
    )
