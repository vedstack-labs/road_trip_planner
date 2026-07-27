"""FastAPI authentication dependencies.

Validates the bearer token, then loads (auto-provisioning on first sight) the
user profile so the agent can pull saved vehicles, previous trips, and stored
preferences without asking again.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import AuthError, Principal, decode_token
from app.db.base import get_session
from app.db.models import User

_bearer = HTTPBearer(auto_error=False, description="Helpsonroad user JWT")


async def get_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    """Extract and validate the caller principal from the Authorization header."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return decode_token(credentials.credentials)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def load_or_provision_user(session: AsyncSession, principal: Principal) -> User:
    """Load the user's profile, provisioning it on first sight from JWT claims."""
    user = await session.get(User, principal.user_id)
    if user is None:
        user = User(
            id=principal.user_id,
            email=principal.email or f"{principal.user_id}@users.helpsonroad.local",
            name=principal.name or "Helpsonroad Driver",
            subscription_tier=principal.subscription_tier,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    elif user.subscription_tier != principal.subscription_tier:
        user.subscription_tier = principal.subscription_tier
        await session.commit()
    return user


async def get_current_user(
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """FastAPI dependency: authenticated user's profile."""
    return await load_or_provision_user(session, principal)


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
DbSession = Annotated[AsyncSession, Depends(get_session)]
