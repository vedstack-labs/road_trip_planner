"""Application settings loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    Values are read from the process environment (and a local ``.env`` file
    during development). Never commit real secrets.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Service ---
    app_name: str = "Helpsonroad Trip Planner Agent"
    environment: str = "development"
    api_prefix: str = "/api/v1"

    # --- Database ---
    # Async SQLAlchemy URL. Postgres in prod; SQLite is used for local/dev/tests.
    database_url: str = "postgresql+asyncpg://helpsonroad:helpsonroad@localhost:5432/helpsonroad"

    # --- Auth (JWT) ---
    jwt_secret: str = "dev-insecure-change-me"
    jwt_algorithm: str = "HS256"
    jwt_issuer: str | None = None
    jwt_audience: str | None = None

    # --- LLM / PydanticAI ---
    # e.g. "anthropic:claude-sonnet-4-6". When unset the app falls back to a
    # deterministic TestModel so the service still boots without an LLM key.
    agent_model: str = "anthropic:claude-sonnet-4-6"
    anthropic_api_key: str | None = None
    agent_use_test_model: bool = False
    # Keep only the most recent N messages of history per turn (bounds latency,
    # token cost, and context growth). Trimmed on whole-turn boundaries.
    agent_history_max_messages: int = 30

    # --- Provider result cache (geocode/places) ---
    provider_cache_ttl_seconds: float = 300.0

    # --- Sharing ---
    share_base_url: str = "https://app.helpsonroad.com/trips/shared"

    # --- External location context ---
    # Official tourism sites used to enrich recommendations per region.
    australia_context_base_url: str = "https://www.australia.com"
    nepal_context_base_url: str = "https://ntb.gov.np"
    location_context_timeout_seconds: float = 6.0
    enable_external_context: bool = True

    # --- Google Maps Platform (optional, key-gated enhancement) ---
    # When set, the agent sources real places, geocoding, and road routing from
    # Google instead of the curated catalog + haversine fallback.
    google_maps_api_key: str | None = None
    prefer_google: bool = True
    google_places_radius_m: int = 60000
    google_timeout_seconds: float = 8.0

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def google_enabled(self) -> bool:
        return self.prefer_google and bool(self.google_maps_api_key)


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
