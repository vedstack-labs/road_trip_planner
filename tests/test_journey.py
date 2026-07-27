"""Journey Mode start, progress, and roadside pause/resume."""

from __future__ import annotations

from app.db.models import Trip, TripStop, User
from app.enums import JourneyStatus
from app.services import journey_service, roadside_service


async def _seed_trip(session, user_id: str = "u-test") -> Trip:
    user = await session.get(User, user_id)
    if user is None:
        user = User(id=user_id, email=f"{user_id}@t.dev", name="Driver")
        session.add(user)
    trip = Trip(
        user_id=user_id,
        title="Test Loop",
        region="australia",
        origin="Sydney",
        destination="Blue Mountains",
        traveller_type="couple",
        mood=["scenic"],
        duration="full_day",
    )
    trip.stops = [
        TripStop(
            stop_order=1, place_name="Echo Point Lookout", stop_type="scenic_lookout",
            latitude=-33.7325, longitude=150.3020,
        ),
        TripStop(
            stop_order=2, place_name="Katoomba Cafe", stop_type="cafe",
            latitude=-33.7148, longitude=150.3120,
        ),
    ]
    session.add(trip)
    await session.commit()
    await session.refresh(trip)
    return trip


async def test_start_journey_activates(client, auth, session):
    trip = await _seed_trip(session)
    resp = await client.post("/api/v1/journey/start", json={"trip_id": trip.id}, headers=auth)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == JourneyStatus.ACTIVE.value
    assert body["trip_id"] == trip.id
    assert body["started_at"] is not None


async def test_start_journey_unknown_trip_404(client, auth):
    resp = await client.post("/api/v1/journey/start", json={"trip_id": "nope"}, headers=auth)
    assert resp.status_code == 404


async def test_roadside_pauses_active_journey_then_resume(session):
    trip = await _seed_trip(session)
    journey = await journey_service.start_journey(
        session, user_id="u-test", trip_id=trip.id
    )
    assert journey.status == JourneyStatus.ACTIVE.value

    handoff = await roadside_service.request_roadside_assistance(
        session, user_id="u-test", reason="My tyre is flat"
    )
    assert handoff.journey_paused is True
    assert handoff.ticket_id.startswith("RSA-")

    paused = await journey_service.get_active_journey(session, user_id="u-test")
    assert paused is not None and paused.status == JourneyStatus.PAUSED.value
    assert paused.roadside_reason == "My tyre is flat"

    resumed = await roadside_service.resume_after_roadside(session, journey=paused)
    assert resumed.status == JourneyStatus.ACTIVE.value
    assert resumed.roadside_reason is None


async def test_journey_progress_reports_next_stops(session):
    trip = await _seed_trip(session)
    journey = await journey_service.start_journey(session, user_id="u-test", trip_id=trip.id)
    prog = await journey_service.progress(session, journey=journey)
    assert prog.status == JourneyStatus.ACTIVE
    assert prog.current_stop == "Echo Point Lookout"
    assert prog.next_attraction == "Echo Point Lookout"
    assert prog.next_restaurant == "Katoomba Cafe"
    assert prog.remaining_stops == 1
