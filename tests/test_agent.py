"""Agent chat endpoint (offline) and tool orchestration (scripted FunctionModel)."""

from __future__ import annotations

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import select

from app.agent.planner_agent import get_agent, run_chat
from app.auth.jwt import Principal
from app.db.models import Trip, User
from app.enums import JourneyStatus
from app.services import journey_service


def _scripted_model(script: list[tuple[str, dict]], final: str) -> FunctionModel:
    """Return a FunctionModel that issues each scripted tool call in turn,
    then a final text response."""
    state = {"step": 0}

    def fn(messages, info: AgentInfo) -> ModelResponse:
        step = state["step"]
        state["step"] += 1
        if step < len(script):
            name, args = script[step]
            return ModelResponse(parts=[ToolCallPart(tool_name=name, args=args)])
        return ModelResponse(parts=[TextPart(final)])

    return FunctionModel(fn)


async def _ensure_user(session, user_id="u-test") -> User:
    user = await session.get(User, user_id)
    if user is None:
        user = User(id=user_id, email=f"{user_id}@t.dev", name="Driver", subscription_tier="premium")
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user


async def test_chat_endpoint_offline_returns_conversation(client, auth):
    first = await client.post("/api/v1/agent/chat", json={"message": "Plan a trip"}, headers=auth)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["conversationId"]
    assert body["response"]

    # Continuing the same conversation reuses the id (history persisted).
    cid = body["conversationId"]
    second = await client.post(
        "/api/v1/agent/chat",
        json={"message": "thanks", "conversation_id": cid},
        headers=auth,
    )
    assert second.status_code == 200
    assert second.json()["conversationId"] == cid


async def test_agent_orchestrates_search_and_save(session):
    user = await _ensure_user(session)
    principal = Principal(user_id=user.id)

    script = [
        ("search_attractions", {"destination": "Sydney", "moods": ["nature", "coffee"]}),
        (
            "save_trip",
            {
                "title": "Sydney Nature & Coffee",
                "origin": "Sydney",
                "destination": "Sydney",
                "traveller_type": "couple",
                "duration": "weekend",
                "moods": ["nature", "coffee"],
                "region": "australia",
                "summary": "Scenic city loop.",
                "stops": [
                    {
                        "place_name": "Bondi Beach",
                        "stop_type": "attraction",
                        "latitude": -33.8908,
                        "longitude": 151.2743,
                        "dwell_minutes": 60,
                    },
                    {
                        "place_name": "The Grounds of Alexandria",
                        "stop_type": "cafe",
                        "latitude": -33.9106,
                        "longitude": 151.1939,
                        "dwell_minutes": 45,
                    },
                ],
            },
        ),
    ]
    model = _scripted_model(script, "Your Sydney itinerary is ready and saved.")

    with get_agent().override(model=model):
        cid, text = await run_chat(
            session, user=user, principal=principal,
            message="Plan a Sydney nature and coffee weekend and save it",
            conversation_id=None,
        )

    assert "saved" in text.lower()
    trips = (await session.execute(select(Trip).where(Trip.user_id == user.id))).scalars().all()
    assert len(trips) == 1
    assert trips[0].title == "Sydney Nature & Coffee"


async def test_agent_triggers_roadside_and_pauses_journey(session):
    user = await _ensure_user(session)
    principal = Principal(user_id=user.id, vehicle_id="v1")

    # Seed and activate a journey.
    trip = Trip(
        user_id=user.id, title="Loop", region="australia", origin="Sydney",
        destination="Blue Mountains", traveller_type="solo", mood=["scenic"], duration="full_day",
    )
    session.add(trip)
    await session.commit()
    await journey_service.start_journey(session, user_id=user.id, trip_id=trip.id)

    model = _scripted_model(
        [("request_roadside_assistance", {"reason": "My tyre is flat"})],
        "I've requested roadside assistance and paused your trip.",
    )
    with get_agent().override(model=model):
        _, text = await run_chat(
            session, user=user, principal=principal,
            message="My tyre is flat", conversation_id=None,
        )

    assert "roadside" in text.lower()
    active = await journey_service.get_active_journey(session, user_id=user.id)
    assert active is not None
    assert active.status == JourneyStatus.PAUSED.value
    assert active.roadside_reason == "My tyre is flat"
