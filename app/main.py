"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api.v1 import agent, auth, journey, trips
from app.config import get_settings
from app.db.base import dispose_engine, init_models

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-create tables only for the file-backed SQLite used in local/dev/test,
    # where it keeps first boot frictionless. Against managed Postgres the schema
    # is owned by migrations: running create_all on every serverless cold start
    # is wasteful and, worse, makes boot hard-depend on DB reachability so a
    # transient connect failure kills the whole function. Skip it there.
    settings = get_settings()
    if settings.is_sqlite:
        await init_models()
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description="Helpsonroad AI Trip Planner Agent (MVP)",
        lifespan=lifespan,
    )

    @app.get("/health", tags=["system"])
    async def health() -> dict:
        return {"status": "ok", "service": settings.app_name, "environment": settings.environment}

    _index = Path(__file__).resolve().parent / "web" / "index.html"

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(_index)

    prefix = settings.api_prefix
    app.include_router(agent.router, prefix=prefix)
    app.include_router(trips.router, prefix=prefix)
    app.include_router(journey.router, prefix=prefix)
    if settings.environment.lower() != "production":
        app.include_router(auth.router, prefix=prefix)

    return app


app = create_app()
