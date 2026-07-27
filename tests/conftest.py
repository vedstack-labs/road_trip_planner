"""Pytest fixtures. Configures an isolated SQLite DB and offline agent."""

from __future__ import annotations

import os
import tempfile

# Configure the environment BEFORE any app module (and its cached settings) load.
_DB_FD, _DB_PATH = tempfile.mkstemp(suffix=".db")
os.environ.update(
    {
        "DATABASE_URL": f"sqlite+aiosqlite:///{_DB_PATH}",
        "JWT_SECRET": "test-secret",
        "ENVIRONMENT": "test",
        "AGENT_USE_TEST_MODEL": "true",
        "ENABLE_EXTERNAL_CONTEXT": "false",
        "SHARE_BASE_URL": "https://share.test/trips",
    }
)

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.auth.jwt import create_access_token  # noqa: E402
from app.db import models  # noqa: E402,F401  (register metadata)
from app.db.base import Base, get_engine, get_sessionmaker  # noqa: E402
from app.main import app  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def _fresh_db():
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def session():
    async with get_sessionmaker()() as s:
        yield s


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def token() -> str:
    return create_access_token(
        user_id="u-test",
        email="driver@test.dev",
        name="Test Driver",
        subscription_tier="premium",
        roles=["driver"],
    )


@pytest.fixture
def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
