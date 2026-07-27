"""Composite plan_trip, provider cache, and history trimming."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.config import Settings, get_settings
from app.enums import Region, StopType, TravellerType, TripDuration
from app.services import planning_service, providers, places_service


@pytest.fixture(autouse=True)
def _clear_cache():
    providers.clear_cache()
    yield
    providers.clear_cache()


async def test_plan_trip_offline_builds_scheduled_ordered_itinerary():
    settings = get_settings()
    assert not settings.google_enabled  # offline path in tests
    itin = await planning_service.plan_trip(
        settings,
        region=Region.AUSTRALIA,
        origin="Sydney",
        destination="Blue Mountains",
        moods=["scenic", "coffee"],
        traveller_type=TravellerType.COUPLE,
        duration=TripDuration.WEEKEND,
        depart_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
    )
    assert 3 <= len(itin.stops) <= 8
    # Orders are sequential from 1.
    assert [s.order for s in itin.stops] == list(range(1, len(itin.stops) + 1))
    # Arrival times are non-decreasing and departures follow arrivals.
    for s in itin.stops:
        assert s.departure_time >= s.arrival_time
    times = [s.arrival_time for s in itin.stops]
    assert times == sorted(times)
    assert itin.total_drive_minutes > 0
    # A dining stop is included, not just sightseeing.
    assert any(s.stop_type in {StopType.CAFE, StopType.RESTAURANT} for s in itin.stops)


async def test_provider_cache_hits_avoid_recompute(monkeypatch):
    settings = get_settings()
    first = await providers.find_attractions(
        settings, region=Region.AUSTRALIA, destination="Blue Mountains",
        traveller_type=None, moods=["scenic"], near=None, limit=3,
    )
    assert first

    # If the cache works, the underlying search is not called again.
    def boom(**kwargs):
        raise AssertionError("catalog search should have been cached")

    monkeypatch.setattr(places_service, "search_attractions", boom)
    second = await providers.find_attractions(
        settings, region=Region.AUSTRALIA, destination="Blue Mountains",
        traveller_type=None, moods=["scenic"], near=None, limit=3,
    )
    assert [p.name for p in second] == [p.name for p in first]


def test_trim_history_keeps_whole_turns():
    from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

    from app.agent.planner_agent import _trim_history

    def turn(text: str):
        return [
            ModelRequest(parts=[UserPromptPart(content=text)]),
            ModelResponse(parts=[TextPart(content="ok:" + text)]),
        ]

    messages = turn("t1") + turn("t2") + turn("t3")  # 6 messages, 3 turns
    trimmed = _trim_history(messages, max_messages=3)
    # Must start on a user-turn boundary, not mid-turn.
    assert isinstance(trimmed[0], ModelRequest)
    assert any(isinstance(p, UserPromptPart) for p in trimmed[0].parts)
    assert len(trimmed) <= 4  # last full turn (and possibly the boundary of t2)


def test_trim_history_noop_when_small():
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    from app.agent.planner_agent import _trim_history

    msgs = [ModelRequest(parts=[UserPromptPart(content="hi")])]
    assert _trim_history(msgs, max_messages=30) is msgs
