"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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

    origins = settings.cors_origin_list
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        # Wildcard origins cannot be combined with credentials per the CORS
        # spec; this API authenticates via bearer token, not cookies.
        allow_credentials=origins != ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["system"])
    async def health() -> dict:
        return {"status": "ok", "service": settings.app_name, "environment": settings.environment}

    @app.get("/", include_in_schema=False)
    async def root() -> JSONResponse:
        return JSONResponse(
            {
                "service": settings.app_name,
                "status": "ok",
                "docs": "/docs",
                "api_prefix": settings.api_prefix,
            }
        )

    prefix = settings.api_prefix
    app.include_router(agent.router, prefix=prefix)
    app.include_router(trips.router, prefix=prefix)
    app.include_router(journey.router, prefix=prefix)
    if settings.environment.lower() != "production":
        app.include_router(auth.router, prefix=prefix)

    return app


app = create_app()
