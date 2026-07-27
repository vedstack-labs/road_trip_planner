"""Async SQLAlchemy engine, session factory, and declarative base."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine, creating it on first use."""
    global _engine
    if _engine is None:
        settings = get_settings()
        connect_args: dict = {}
        engine_kwargs: dict = {"echo": False}
        if settings.is_sqlite:
            connect_args["check_same_thread"] = False
            engine_kwargs["pool_pre_ping"] = True
        else:
            # Serverless (e.g. Vercel) + transaction-mode pooler (Supabase
            # Supavisor / PgBouncer) safe config for asyncpg — the SQLAlchemy
            # docs' recommended combination:
            #  - NullPool: never reuse a connection across a frozen invocation
            #    (a pooled socket resumed on a new loop is what makes uvloop's
            #    create_connection raise "[Errno 16] Device or resource busy").
            #  - statement_cache_size / prepared_statement_cache_size = 0 and a
            #    unique prepared-statement name per prepare: transaction poolers
            #    multiplex sessions, so numbered/cached prepared statements
            #    collide or vanish. Disable caching and randomize the names.
            engine_kwargs["poolclass"] = NullPool
            connect_args["statement_cache_size"] = 0
            connect_args["prepared_statement_cache_size"] = 0
            connect_args["prepared_statement_name_func"] = lambda: f"__asyncpg_{uuid4()}__"
        _engine = create_async_engine(
            settings.database_url,
            connect_args=connect_args,
            **engine_kwargs,
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a scoped async session."""
    factory = get_sessionmaker()
    async with factory() as session:
        yield session


async def init_models() -> None:
    """Create tables for all registered models (dev/test convenience)."""
    # Import models so they register on the metadata before create_all.
    from app.db import models  # noqa: F401

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    """Dispose the engine and reset module state (used on shutdown/tests)."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
