# Helpsonroad AI Trip Planner Agent (MVP)

An AI driving companion that plans personalised road trips (Australia and Nepal,
extensible to more regions) and hands over to roadside assistance mid-journey.
Built per the PRD: **FastAPI + PydanticAI + PostgreSQL + JWT**, containerised for
**Kubernetes**.

The agent recommends scenic routes, attractions, cafés, restaurants, lookouts,
and rest stops from the traveller's duration, party, and mood — then saves,
shares, and drives the itinerary in **Journey Mode**. For Australia it enriches
recommendations with **live context from Tourism Australia (australia.com)**.

---

## Architecture

```
Web app ──JWT──▶ Trip Planner API (FastAPI)
                     │
                 PydanticAI Agent  ──dynamic prompt loads user vehicles/trips/prefs
                     │
                 Tool Layer  (the LLM only ever calls tools)
                     │
   ┌─────────────────┼───────────────────────────────────────────┐
   Places   Restaurant   Maps (route/ETA)   Trip   Journey   Roadside
   Service    Service        Service        Svc     Svc        Svc
   │            │              │              │       │          │
 Catalog +   Catalog       haversine +      PostgreSQL (users, trips, trip_stops,
 gazetteer   (ratings)     2-opt routing     journeys, conversations, vehicles)
   │
 Location context providers ── australia.com (live) / Nepal (curated)
```

Key design points:
- **The LLM never touches external services or the DB directly** — only via typed
  tools in `app/agent/tools.py`.
- **The agent is never public**: every request requires a valid Helpsonroad JWT.
- **Stateless replicas**: chat history is persisted in the `conversations` table
  (serialized PydanticAI messages), so the service scales horizontally on K8s.
- **No fabrication**: the agent only recommends places returned by the tools; the
  catalog is curated reference data with real coordinates.

---

## Project layout

```
app/
  config.py            Settings (env-driven)
  enums.py             Region, TripDuration, TravellerType, Mood, StopType, JourneyStatus
  db/                  Async engine, session, ORM models
  auth/                JWT issue/validate + FastAPI current-user dependency
  data/                Curated place catalogs (australia.json, nepal.json)
  services/            Places, Restaurant, Maps, Trip, Journey, Roadside + catalog/geocode
  locations/           Region context providers (australia.com live, nepal curated)
  agent/               AgentDeps, tools, planner_agent (prompt + model + chat runner)
  api/v1/              agent, trips, journey, auth (dev-token) routers
  main.py              FastAPI app + lifespan
tests/                 pytest suite (auth, services, trips API, journey, agent)
k8s/                   Deployment, Service, ConfigMap, Secret example
Dockerfile, docker-compose.yml, .env.example
```

---

## Quickstart (local, no server dependencies)

Uses `uv` and a SQLite database; the offline model boots without any LLM key.

```bash
uv venv --python 3.12
uv pip install -e ".[dev]"

DATABASE_URL="sqlite+aiosqlite:///./dev.db" \
JWT_SECRET="dev-secret-change-me" \
AGENT_USE_TEST_MODEL=true \
.venv/bin/uvicorn app.main:app --reload
```

Then:

```bash
# 1. Get a dev JWT (non-production only)
JWT=$(curl -s -X POST localhost:8000/api/v1/auth/dev-token \
  -d '{"user_id":"me","subscription_tier":"premium"}' | jq -r .access_token)

# 2. Chat with the agent
curl -s -X POST localhost:8000/api/v1/agent/chat \
  -H "Authorization: Bearer $JWT" -H 'Content-Type: application/json' \
  -d '{"message":"Plan a weekend trip from Sydney for two who love nature and coffee."}'
```

### With PostgreSQL via Docker Compose

```bash
docker compose up --build
# API on :8000, Postgres on :5432
```

### Enabling real AI generation

The offline `TestModel` fallback lets the service boot and exercises every path
except real LLM reasoning. For real itineraries set an LLM provider:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export AGENT_MODEL=anthropic:claude-sonnet-4-6
export AGENT_USE_TEST_MODEL=false
```

Any PydanticAI-supported model string works for `AGENT_MODEL`.

---

## API

All endpoints are under `/api/v1` and require `Authorization: Bearer <JWT>`
(except `GET /trips/shared/{token}` and, in non-prod, `POST /auth/dev-token`).

| Method | Path | Purpose |
|---|---|---|
| POST | `/agent/chat` | Talk to the agent. `{message, conversation_id?}` → `{conversationId, response}` |
| POST | `/agent/chat/stream` | Same, streamed as SSE (`data: {json}` — `delta` chunks then a `done` event with `conversation_id`) |
| POST | `/trips` | Save an itinerary |
| GET  | `/trips` | List the user's saved trips |
| GET  | `/trips/{id}` | Retrieve one itinerary |
| POST | `/trips/{id}/share` | Generate a shareable link |
| GET  | `/trips/shared/{token}` | Public read of a shared itinerary (no auth) |
| POST | `/journey/start` | Activate Journey Mode for a trip |
| GET  | `/journey/active` | Live progress of the caller's active/paused journey |
| GET  | `/journey/{id}` | Live progress of a specific journey |
| POST | `/journey/{id}/advance` | Advance to the next stop (auto-completes past the last) |
| POST | `/journey/{id}/resume` | Resume a paused journey (after roadside) |
| POST | `/journey/{id}/complete` | Mark the journey completed |
| GET  | `/health` | Liveness/readiness |
| POST | `/auth/dev-token` | Issue a JWT (non-production only) |

### JWT claims

`sub` (user id), `subscription_tier`, `roles`, optional `vehicle_id`, `email`,
`name`. On first authenticated request the user profile is auto-provisioned; the
agent then loads saved vehicles, previous trips, and preferences without asking.

---

## Agent tools

`plan_trip` (composite — drafts a full ordered, scheduled itinerary in one call),
`get_location_context`, `search_attractions`, `search_restaurants`,
`optimise_route`, `estimate_drive_time`, `save_trip`, `load_saved_trip`,
`share_trip`, `start_journey`, `get_journey_progress`, `advance_stop`,
`resume_journey`, `request_roadside_assistance`.

**Journey + safety:** when a driver reports a breakdown ("my tyre is flat") during
an active journey, the agent calls `request_roadside_assistance`, which pauses the
journey (`ACTIVE → PAUSED`), raises a roadside ticket, and hands off to the
roadside workflow. `resume_after_roadside` returns it to `ACTIVE` — the user never
leaves the trip.

### Performance & cost

- **Streaming** (`/agent/chat/stream`): tokens stream over SSE via `agent.iter`,
  which drives the full tool loop (search → route → save) while streaming, so
  time-to-first-token is ~1-2s instead of waiting for the whole turn.
- **Composite `plan_trip` tool** collapses the search/route/schedule pipeline into
  one server-side call, cutting LLM round-trips (and latency) sharply.
- **History trimming** (`AGENT_HISTORY_MAX_MESSAGES`, default 30) bounds context
  growth on a whole-turn boundary so tool-call/return pairs stay intact.
- **Provider cache** (`PROVIDER_CACHE_TTL_SECONDS`, default 300) memoises
  geocode/place lookups to cut latency and Google spend.

---

## Regions & location context

Supported regions: **Australia** and **Nepal** (`app/enums.Region`). Adding a
region = drop a `app/data/<region>.json` catalog, add gazetteer entries, and
register a `LocationProvider` in `app/locations/__init__.py`.

- **Australia** context is fetched live from Tourism Australia (australia.com)
  destination guide pages; failures fall back to a curated national blurb.
- **Nepal** context is fetched live from the Nepal Tourism Board
  (ntb.gov.np, e.g. `/en/pokhara`, `/en/chitwan-national-park`); failures fall
  back to curated blurbs. Both providers share one fetch/extract helper in
  `app/locations/base.py`.

> Without a Google key the place catalog (`app/data/*.json`) is curated reference
> data with real, well-known landmarks and approximate public coordinates. Set
> `GOOGLE_MAPS_API_KEY` (below) to source live places instead — the catalog then
> becomes the offline fallback.

## Google Maps Platform (optional upgrade)

Set `GOOGLE_MAPS_API_KEY` and the agent upgrades from curated data + haversine to
live Google data. Everything routes through `app/services/providers.py`, which
prefers Google and **falls back automatically** (per call) on any error, empty
result, or missing key — so the app never hard-depends on Google.

| Capability | Google API | Fallback |
|---|---|---|
| Attractions / cafés / restaurants (live ratings, hours) | Places API (New) `places:searchText` | curated `app/data/*.json` |
| Origin/destination coordinates | Geocoding API | `GAZETTEER` in `catalog.py` |
| Road distance, drive time, waypoint ordering | Routes API `computeRoutes` (`optimizeWaypointOrder`) | haversine + nearest-neighbour/2-opt |

Enable it:

```bash
export GOOGLE_MAPS_API_KEY=AIza...   # needs Places API (New), Geocoding, Routes enabled
export PREFER_GOOGLE=true            # default; set false to force the offline path
```

Enable these APIs on the key in Google Cloud: **Places API (New)**, **Geocoding
API**, **Routes API**. Client code: `app/services/google_maps.py`.


---

## Testing

```bash
.venv/bin/python -m pytest
```

Covers JWT guarding and claim round-trips, the maps service (haversine +
2-opt optimality vs brute force), places/restaurant ranking, the trips API
(CRUD, sharing, per-user isolation), Journey Mode (start/progress and the
roadside pause→resume transition), and the agent — both the offline chat path and
full tool orchestration driven by a scripted `FunctionModel` (search → save;
breakdown → roadside pause).

---

## Kubernetes

```bash
kubectl apply -f k8s/configmap.yaml
# create the real secret (never commit it) — see k8s/secret.example.yaml
kubectl create secret generic trip-planner-secrets \
  --from-literal=JWT_SECRET=... \
  --from-literal=DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-...
kubectl apply -f k8s/deployment.yaml -f k8s/service.yaml
```

Readiness/liveness probes hit `/health`; 3 replicas by default (stateless).

---

## Out of scope (per PRD)

Hotel/camping bookings, events, offline mode, voice, EV charging, fuel
optimisation, collaborative planning.
