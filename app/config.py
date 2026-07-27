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
    # Comma-separated allowlist of origins permitted to call the API from a
    # browser (the consuming app). "*" allows any origin (bearer-token APIs
    # only; wildcard + credentials is disallowed by the CORS spec).
    cors_origins: str = "*"

    # --- Database ---
    # Async SQLAlchemy URL. Postgres in prod; SQLite is used for local/dev/tests.
    database_url: str = "postgresql+asyncpg://helpsonroad:helpsonroad@localhost:5432/helpsonroad"

    # --- Auth (JWT) ---
    # HS256 shared secret is used for the legacy/dev-token flow (symmetric).
    jwt_secret: str = "dev-insecure-change-me"
    jwt_algorithm: str = "HS256"  # algorithm used when *issuing* dev tokens
    jwt_issuer: str | None = None
    jwt_audience: str | None = None
    # Asymmetric verification (e.g. Supabase/Lovable Cloud, which sign with
    # ES256). When set, tokens whose header alg is asymmetric are verified
    # against the JWKS at this URL; the matching key is chosen by `kid`.
    #   JWT_JWKS_URL=https://<project>.supabase.co/auth/v1/.well-known/jwks.json
    #   JWT_AUDIENCE=authenticated
    jwt_jwks_url: str | None = None
    # Comma-separated allow-list of accepted signing algorithms on decode.
    #   JWT_ALGORITHMS=ES256,RS256,HS256
    jwt_algorithms: str = "HS256"

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
    def cors_origin_list(self) -> list[str]:
        raw = self.cors_origins.strip()
        if raw == "*":
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]

    @property
    def jwt_algorithm_list(self) -> list[str]:
        return [a.strip() for a in self.jwt_algorithms.split(",") if a.strip()]

    @property
    def google_enabled(self) -> bool:
        return self.prefer_google and bool(self.google_maps_api_key)


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
