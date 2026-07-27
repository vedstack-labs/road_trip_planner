"""Dependency container injected into every agent tool call."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import Principal
from app.db.models import User
from app.enums import Region


@dataclass
class AgentDeps:
    """Per-request state available to tools via ``RunContext.deps``."""

    session: AsyncSession
    user: User
    principal: Principal
    default_region: Region = Region.AUSTRALIA

    @property
    def user_id(self) -> str:
        return self.user.id

    @property
    def preferences(self) -> dict:
        return self.user.preferences or {}
