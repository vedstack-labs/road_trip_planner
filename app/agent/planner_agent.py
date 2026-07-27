"""The Trip Planner PydanticAI agent: construction, prompt, and chat runner."""

from __future__ import annotations

import logging
import os
from functools import lru_cache

from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    PartDeltaEvent,
    TextPartDelta,
    UserPromptPart,
)
from pydantic_ai.models import Model
from pydantic_ai.models.test import TestModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.deps import AgentDeps
from app.agent.tools import register_tools
from app.auth.jwt import Principal
from app.config import Settings, get_settings
from app.db.models import Conversation, Trip, User, Vehicle
from app.enums import Region

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are the Helpsonroad Trip Planner, an AI driving companion that designs \
personalised Australian (and Nepal) road trips and can hand over to roadside \
assistance at any time.

How you work:
- Plan trips using the tools; never invent locations, ratings, or opening hours. \
Only recommend places returned by the tools.
- Call get_location_context to ground the trip in official tourism information \
(Tourism Australia for Australia). Prioritise official tourism information.
- To draft an itinerary, prefer the single ``plan_trip`` tool — it finds places,
optimises the driving order, schedules arrival/departure times, and adds official
context in one step. Only fall back to search_attractions/search_restaurants/
optimise_route/estimate_drive_time when you need to tweak a specific detail.
- Itineraries have 3-8 stops with a clear driving order, estimated arrival times,
and time to spend at each stop.
- Prefer scenic roads where practical but avoid excessive detours.
- Recommend highly rated restaurants and cafes near the route.
- For longer journeys (roughly every two hours of driving), include a rest stop.
- For family trips, prefer family-friendly recommendations.
- Ask a follow-up question ONLY when a required detail (origin, region, duration, \
travellers, or mood) is genuinely missing and cannot be inferred from the user's \
profile. Keep responses concise and explain why each place was chosen.
- Supported regions today: Australia and Nepal. If the user names another place, \
say it is not yet supported.

Journey & safety:
- When the user says they want to start the trip, call start_journey. During the
journey use get_journey_progress (current stop, next attraction/restaurant, ETA)
and advance_stop when they move on.
- If the driver reports a breakdown or emergency during a journey (e.g. "my tyre \
is flat"), immediately call request_roadside_assistance; the trip pauses. Call
resume_journey once assistance is done. The user never leaves the trip.

You can also save trips (save_trip), retrieve them (load_saved_trip), and create \
shareable links (share_trip)."""


def _resolve_model(settings: Settings) -> Model | str:
    # Offline/boot fallback. Without an LLM the agent cannot do real planning, so
    # it responds without calling tools (call_tools=[]) — safe and instant.
    offline_note = (
        "Trip planning requires an LLM provider. Set ANTHROPIC_API_KEY and "
        "AGENT_MODEL to enable full itinerary generation."
    )
    if settings.agent_use_test_model:
        return TestModel(call_tools=[], custom_output_text=offline_note)
    if settings.anthropic_api_key:
        os.environ.setdefault("ANTHROPIC_API_KEY", settings.anthropic_api_key)
        return settings.agent_model
    logger.warning(
        "No LLM API key configured; falling back to an offline no-tool responder. "
        "Set ANTHROPIC_API_KEY and AGENT_MODEL for real generation."
    )
    return TestModel(call_tools=[], custom_output_text=offline_note)


@lru_cache
def get_agent() -> Agent[AgentDeps]:
    """Construct (once) the trip-planner agent with tools and prompts."""
    settings = get_settings()
    agent: Agent[AgentDeps] = Agent(
        _resolve_model(settings),
        deps_type=AgentDeps,
        system_prompt=SYSTEM_PROMPT,
        retries=2,
    )

    @agent.system_prompt(dynamic=True)
    async def _user_context(ctx: RunContext[AgentDeps]) -> str:
        """Load saved vehicles, previous trips, and preferences up front."""
        session = ctx.deps.session
        user = ctx.deps.user
        vehicles = (
            await session.execute(select(Vehicle).where(Vehicle.user_id == user.id))
        ).scalars().all()
        trip_count = (
            await session.execute(
                select(func.count(Trip.id)).where(Trip.user_id == user.id)
            )
        ).scalar_one()

        lines = [
            f"Authenticated user: {user.name} (tier: {user.subscription_tier}).",
            f"Default region: {ctx.deps.default_region.value}.",
            f"Saved trips on file: {trip_count}.",
        ]
        if vehicles:
            desc = ", ".join(
                " ".join(filter(None, [v.make, v.model, f"({v.registration})" if v.registration else None]))
                or "vehicle"
                for v in vehicles
            )
            lines.append(f"Saved vehicles: {desc}.")
        prefs = ctx.deps.preferences
        if prefs:
            lines.append(f"Saved preferences: {prefs}.")
        lines.append("Use these details instead of asking the user to repeat them.")
        return " ".join(lines)

    register_tools(agent)
    return agent


def _default_region(user: User) -> Region:
    pref = (user.preferences or {}).get("region")
    if pref:
        try:
            return Region(str(pref).lower())
        except ValueError:
            pass
    return Region.AUSTRALIA


def _trim_history(messages: list[ModelMessage], max_messages: int) -> list[ModelMessage]:
    """Keep only the most recent messages, cut on a whole-turn boundary.

    A turn begins with a ModelRequest containing a UserPromptPart; starting there
    keeps tool-call/tool-return pairs intact (Anthropic rejects an orphaned
    tool_result), so we never slice mid-turn.
    """
    if max_messages <= 0 or len(messages) <= max_messages:
        return messages
    for i in range(len(messages) - max_messages, len(messages)):
        m = messages[i]
        if isinstance(m, ModelRequest) and any(isinstance(p, UserPromptPart) for p in m.parts):
            return messages[i:]
    return messages


def _make_deps(session: AsyncSession, user: User, principal: Principal) -> AgentDeps:
    return AgentDeps(
        session=session, user=user, principal=principal,
        default_region=_default_region(user),
    )


async def _load_conversation(
    session: AsyncSession, user: User, conversation_id: str | None
) -> tuple[Conversation | None, list[ModelMessage]]:
    conversation: Conversation | None = None
    if conversation_id:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is not None and conversation.user_id != user.id:
            conversation = None  # never leak another user's conversation
    history: list[ModelMessage] = []
    if conversation is not None and conversation.messages:
        history = ModelMessagesTypeAdapter.validate_python(conversation.messages)
    history = _trim_history(history, get_settings().agent_history_max_messages)
    return conversation, history


async def _persist(
    session: AsyncSession, conversation: Conversation | None, user: User,
    messages: list[ModelMessage],
) -> Conversation:
    dumped = ModelMessagesTypeAdapter.dump_python(messages, mode="json")
    if conversation is None:
        conversation = Conversation(user_id=user.id, messages=dumped)
        session.add(conversation)
    else:
        conversation.messages = dumped
    await session.commit()
    await session.refresh(conversation)
    return conversation


async def run_chat(
    session: AsyncSession,
    *,
    user: User,
    principal: Principal,
    message: str,
    conversation_id: str | None,
) -> tuple[str, str]:
    """Run one chat turn, persisting (trimmed) message history.

    Returns ``(conversation_id, response_text)``.
    """
    conversation, history = await _load_conversation(session, user, conversation_id)
    result = await get_agent().run(
        message, deps=_make_deps(session, user, principal), message_history=history
    )
    conversation = await _persist(session, conversation, user, result.all_messages())
    output = result.output
    return conversation.id, output if isinstance(output, str) else str(output)


async def run_chat_stream(
    session: AsyncSession,
    *,
    user: User,
    principal: Principal,
    message: str,
    conversation_id: str | None,
):
    """Stream one chat turn as incremental text, then persist history.

    Yields dicts: ``{"type": "delta", "text": ...}`` for each chunk and a final
    ``{"type": "done", "conversation_id": ...}``.
    """
    conversation, history = await _load_conversation(session, user, conversation_id)
    deps = _make_deps(session, user, principal)
    agent = get_agent()
    # agent.iter drives the full graph (text + tool calls); run_stream alone would
    # stop at the first model response and skip tool execution.
    async with agent.iter(message, deps=deps, message_history=history) as run:
        async for node in run:
            if Agent.is_model_request_node(node):
                async with node.stream(run.ctx) as stream:
                    async for event in stream:
                        if isinstance(event, PartDeltaEvent) and isinstance(
                            event.delta, TextPartDelta
                        ):
                            if event.delta.content_delta:
                                yield {"type": "delta", "text": event.delta.content_delta}
        messages = run.result.all_messages()
    conversation = await _persist(session, conversation, user, messages)
    yield {"type": "done", "conversation_id": conversation.id}
