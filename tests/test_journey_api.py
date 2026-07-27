"""Journey Mode loop over HTTP: start → progress → advance → resume → complete."""

from __future__ import annotations

from app.db.models import Trip, TripStop, User
from app.enums import JourneyStatus


async def _seed_trip(session, user_id: str = "u-test") -> Trip:
    if await session.get(User, user_id) is None:
        session.add(User(id=user_id, email=f"{user_id}@t.dev", name="Driver"))
    trip = Trip(
        user_id=user_id, title="Loop", region="australia", origin="Sydney",
        destination="Blue Mountains", traveller_type="couple", mood=["scenic"], duration="full_day",
    )
    trip.stops = [
        TripStop(stop_order=1, place_name="Echo Point", stop_type="scenic_lookout",
                 latitude=-33.7325, longitude=150.3020),
        TripStop(stop_order=2, place_name="Katoomba Cafe", stop_type="cafe",
                 latitude=-33.7148, longitude=150.3120),
    ]
    session.add(trip)
    await session.commit()
    await session.refresh(trip)
    return trip


async def test_full_journey_loop(client, auth, session):
    trip = await _seed_trip(session)

    started = await client.post("/api/v1/journey/start", json={"trip_id": trip.id}, headers=auth)
    assert started.status_code == 201
    jid = started.json()["id"]

    # Live progress: at first stop, next restaurant is the cafe.
    prog = await client.get("/api/v1/journey/active", headers=auth)
    assert prog.status_code == 200
    p = prog.json()
    assert p["current_stop"] == "Echo Point"
    assert p["next_restaurant"] == "Katoomba Cafe"
    assert p["remaining_stops"] == 1

    # Advance to the second (last) stop.
    adv = await client.post(f"/api/v1/journey/{jid}/advance", headers=auth)
    assert adv.status_code == 200
    assert adv.json()["current_stop"] == "Katoomba Cafe"
    assert adv.json()["remaining_stops"] == 0

    # Advancing past the last stop auto-completes.
    adv2 = await client.post(f"/api/v1/journey/{jid}/advance", headers=auth)
    assert adv2.status_code == 200
    assert adv2.json()["status"] == JourneyStatus.COMPLETED.value


async def test_resume_after_pause_and_advance_conflict(client, auth, session):
    trip = await _seed_trip(session)
    started = await client.post("/api/v1/journey/start", json={"trip_id": trip.id}, headers=auth)
    jid = started.json()["id"]

    # Simulate a roadside pause through the service layer.
    from app.services import roadside_service
    await roadside_service.request_roadside_assistance(
        session, user_id="u-test", reason="Flat tyre"
    )

    # Advancing a paused journey is a conflict.
    conflict = await client.post(f"/api/v1/journey/{jid}/advance", headers=auth)
    assert conflict.status_code == 409

    # Resume restores ACTIVE and clears the roadside reason.
    resumed = await client.post(f"/api/v1/journey/{jid}/resume", headers=auth)
    assert resumed.status_code == 200
    assert resumed.json()["status"] == JourneyStatus.ACTIVE.value
    assert resumed.json()["roadside_reason"] is None


async def test_active_journey_404_when_none(client, auth):
    resp = await client.get("/api/v1/journey/active", headers=auth)
    assert resp.status_code == 404


async def test_journey_isolation(client, auth, session):
    trip = await _seed_trip(session)
    started = await client.post("/api/v1/journey/start", json={"trip_id": trip.id}, headers=auth)
    jid = started.json()["id"]

    from app.auth.jwt import create_access_token
    other = create_access_token(user_id="intruder")
    resp = await client.get(
        f"/api/v1/journey/{jid}", headers={"Authorization": f"Bearer {other}"}
    )
    assert resp.status_code == 404
