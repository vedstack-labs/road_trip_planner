"""Agent tools. The LLM reaches business logic and data ONLY through these.

Every tool is thin: parse/normalise arguments, call a service, return a typed
result. No tool talks to an external service directly except via the service
layer, and none is reachable without an authenticated request (deps carry the
resolved user).
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic_ai import Agent, RunContext

from app.agent.deps import AgentDeps
from app.enums import Region, TravellerType, TripDuration
from app.locations import LocationContext, get_location_provider
from app.config import get_settings
from app.services import journey_service, planning_service, providers, roadside_service, trip_service
from app.services.catalog import Place, geocode
from app.services.maps_service import (
    Coordinate,
    DriveEstimate,
    RoutePlan,
    RouteStopInput,
)
from app.schemas.journey import JourneyOut, JourneyProgress
from app.schemas.trip import ShareResponse, StopInput, TripCreate, TripOut
from app.services.roadside_service import RoadsideHandoff


def _region(value: str | None, deps: AgentDeps) -> Region:
    if value:
        try:
            return Region(value.strip().lower())
        except ValueError:
            pass
    return deps.default_region


def _traveller(value: str | None) -> TravellerType | None:
    if not value:
        return None
    try:
        return TravellerType(value.strip().lower())
    except ValueError:
        return None


def _moods(values: list[str] | None) -> list[str]:
    return [v.strip().lower() for v in (values or []) if v.strip()]


def _duration(value: str | None) -> TripDuration:
    if value:
        try:
            return TripDuration(value.strip().lower())
        except ValueError:
            pass
    return TripDuration.FULL_DAY


def register_tools(agent: Agent[AgentDeps]) -> None:
    """Register all trip-planner tools on the given agent."""

    @agent.tool
    async def get_location_context(
        ctx: RunContext[AgentDeps], destination: str, region: str | None = None
    ) -> LocationContext:
        """Fetch authoritative destination context.

        For Australia this pulls a live summary from Tourism Australia
        (australia.com); other regions return curated official context. Use this
        to enrich recommendations and to ground descriptions in real sources.
        """
        provider = get_location_provider(_region(region, ctx.deps))
        return await provider.get_context(destination)

    @agent.tool
    async def plan_trip(
        ctx: RunContext[AgentDeps],
        origin: str,
        destination: str,
        duration: str,
        traveller_type: str,
        moods: list[str] | None = None,
        region: str | None = None,
        max_stops: int | None = None,
    ) -> planning_service.PlannedItinerary:
        """Draft a complete itinerary in ONE step: finds attractions/cafes, orders
        them into the optimal driving route, schedules arrival/departure times, and
        adds official destination context. Prefer this over calling search/route/
        estimate tools separately. Then call save_trip to persist it."""
        return await planning_service.plan_trip(
            get_settings(),
            region=_region(region, ctx.deps),
            origin=origin,
            destination=destination,
            moods=_moods(moods),
            traveller_type=_traveller(traveller_type) or TravellerType.SOLO,
            duration=_duration(duration),
            max_stops=max_stops,
        )

    @agent.tool
    async def search_attractions(
        ctx: RunContext[AgentDeps],
        destination: str,
        moods: list[str] | None = None,
        traveller_type: str | None = None,
        region: str | None = None,
        limit: int = 8,
    ) -> list[Place]:
        """Return attractions, scenic lookouts, and rest stops matching the
        destination, traveller type, and mood(s)."""
        settings = get_settings()
        region = _region(region, ctx.deps)
        near = geocode(destination)
        return await providers.find_attractions(
            settings,
            region=region,
            destination=destination,
            traveller_type=_traveller(traveller_type),
            moods=_moods(moods),
            near=Coordinate(latitude=near[0], longitude=near[1]) if near else None,
            limit=max(1, min(limit, 12)),
        )

    @agent.tool
    async def search_restaurants(
        ctx: RunContext[AgentDeps],
        destination: str,
        moods: list[str] | None = None,
        traveller_type: str | None = None,
        region: str | None = None,
        cafes_only: bool = False,
        limit: int = 5,
    ) -> list[Place]:
        """Return highly rated restaurants and cafes near the route, with
        ratings and opening hours."""
        settings = get_settings()
        region = _region(region, ctx.deps)
        near = geocode(destination)
        return await providers.find_restaurants(
            settings,
            region=region,
            destination=destination,
            traveller_type=_traveller(traveller_type),
            moods=_moods(moods),
            near=Coordinate(latitude=near[0], longitude=near[1]) if near else None,
            cafes_only=cafes_only,
            limit=max(1, min(limit, 10)),
        )

    @agent.tool
    async def optimise_route(
        ctx: RunContext[AgentDeps],
        stops: list[RouteStopInput],
        origin: str | None = None,
        scenic: bool = True,
    ) -> RoutePlan:
        """Order the selected stops into the optimal driving sequence,
        preferring scenic roads while avoiding excessive detours."""
        settings = get_settings()
        origin_coord = (
            await providers.geocode_place(settings, origin, _region(None, ctx.deps))
            if origin
            else None
        )
        return await providers.plan_route(
            settings, stops=stops, origin=origin_coord, scenic=scenic
        )

    @agent.tool
    async def estimate_drive_time(
        ctx: RunContext[AgentDeps],
        origin_latitude: float,
        origin_longitude: float,
        destination_latitude: float,
        destination_longitude: float,
        scenic: bool = False,
    ) -> DriveEstimate:
        """Return driving time, ETA, and distance between two coordinates."""
        return await providers.leg_estimate(
            get_settings(),
            origin=Coordinate(latitude=origin_latitude, longitude=origin_longitude),
            destination=Coordinate(latitude=destination_latitude, longitude=destination_longitude),
            depart_at=datetime.now(timezone.utc),
            scenic=scenic,
        )

    @agent.tool
    async def save_trip(
        ctx: RunContext[AgentDeps],
        title: str,
        origin: str,
        destination: str,
        traveller_type: str,
        duration: str,
        stops: list[StopInput],
        moods: list[str] | None = None,
        region: str | None = None,
        summary: str | None = None,
    ) -> TripOut:
        """Persist the generated itinerary as a saved trip for the user."""
        data = TripCreate(
            title=title,
            region=_region(region, ctx.deps),
            origin=origin,
            destination=destination,
            traveller_type=TravellerType(traveller_type.strip().lower()),
            mood=_moods(moods),
            duration=duration.strip().lower(),
            summary=summary,
            stops=stops,
        )
        trip = await trip_service.save_trip(ctx.deps.session, user_id=ctx.deps.user_id, data=data)
        return trip_service.to_trip_out(trip)

    @agent.tool
    async def load_saved_trip(
        ctx: RunContext[AgentDeps], trip_id: str | None = None
    ) -> TripOut | list[dict]:
        """Load a previously saved trip by id, or list the user's saved trips
        when no id is given."""
        if trip_id:
            trip = await trip_service.get_trip(
                ctx.deps.session, user_id=ctx.deps.user_id, trip_id=trip_id
            )
            return trip_service.to_trip_out(trip)
        items = await trip_service.list_trips(ctx.deps.session, user_id=ctx.deps.user_id)
        return [i.model_dump(mode="json") for i in items]

    @agent.tool
    async def share_trip(ctx: RunContext[AgentDeps], trip_id: str) -> ShareResponse:
        """Generate a secure shareable link for a saved trip."""
        return await trip_service.share_trip(
            ctx.deps.session, user_id=ctx.deps.user_id, trip_id=trip_id
        )

    @agent.tool
    async def start_journey(ctx: RunContext[AgentDeps], trip_id: str) -> JourneyOut:
        """Activate Journey Mode for a saved trip."""
        journey = await journey_service.start_journey(
            ctx.deps.session, user_id=ctx.deps.user_id, trip_id=trip_id
        )
        return JourneyOut.model_validate(journey, from_attributes=True)

    @agent.tool
    async def get_journey_progress(ctx: RunContext[AgentDeps]) -> JourneyProgress | dict:
        """Report the driver's active journey: current stop, next attraction, next
        restaurant, remaining stops, and remaining drive time."""
        journey = await journey_service.get_active_journey(
            ctx.deps.session, user_id=ctx.deps.user_id
        )
        if journey is None:
            return {"active": False, "message": "No active journey."}
        return await journey_service.progress(ctx.deps.session, journey=journey)

    @agent.tool
    async def advance_stop(ctx: RunContext[AgentDeps]) -> JourneyProgress | dict:
        """Advance the active journey to the next stop (auto-completes past the
        last stop). Use when the driver says they've arrived or want to move on."""
        journey = await journey_service.get_active_journey(
            ctx.deps.session, user_id=ctx.deps.user_id
        )
        if journey is None:
            return {"active": False, "message": "No active journey to advance."}
        try:
            journey = await journey_service.advance_stop(ctx.deps.session, journey=journey)
        except journey_service.JourneyStateError as exc:
            return {"error": str(exc)}
        return await journey_service.progress(ctx.deps.session, journey=journey)

    @agent.tool
    async def resume_journey(ctx: RunContext[AgentDeps]) -> JourneyOut | dict:
        """Resume a paused journey after roadside assistance completes."""
        journey = await journey_service.get_active_journey(
            ctx.deps.session, user_id=ctx.deps.user_id
        )
        if journey is None:
            return {"active": False, "message": "No paused journey to resume."}
        try:
            journey = await journey_service.resume_journey(ctx.deps.session, journey=journey)
        except journey_service.JourneyStateError as exc:
            return {"error": str(exc)}
        return JourneyOut.model_validate(journey, from_attributes=True)

    @agent.tool
    async def request_roadside_assistance(
        ctx: RunContext[AgentDeps], reason: str
    ) -> RoadsideHandoff:
        """Transition to the roadside workflow, pausing any active journey.

        Call this immediately when the driver reports a breakdown (e.g. "my tyre
        is flat"). The journey resumes automatically once assistance completes.
        """
        return await roadside_service.request_roadside_assistance(
            ctx.deps.session,
            user_id=ctx.deps.user_id,
            reason=reason,
            vehicle_id=ctx.deps.principal.vehicle_id,
        )
