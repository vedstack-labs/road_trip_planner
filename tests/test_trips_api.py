"""Trip CRUD, sharing, and per-user isolation via the HTTP API."""

from __future__ import annotations

from app.auth.jwt import create_access_token

TRIP_PAYLOAD = {
    "title": "Sydney Nature & Coffee Weekend",
    "region": "australia",
    "origin": "Sydney",
    "destination": "Blue Mountains",
    "traveller_type": "couple",
    "mood": ["nature", "coffee"],
    "duration": "weekend",
    "summary": "A scenic weekend loop.",
    "stops": [
        {
            "place_name": "Echo Point Lookout",
            "stop_type": "scenic_lookout",
            "latitude": -33.7325,
            "longitude": 150.3020,
            "dwell_minutes": 45,
        },
        {
            "place_name": "Katoomba Street Cafes",
            "stop_type": "cafe",
            "latitude": -33.7148,
            "longitude": 150.3120,
            "dwell_minutes": 30,
        },
    ],
}


async def test_create_get_list_trip(client, auth):
    created = await client.post("/api/v1/trips", json=TRIP_PAYLOAD, headers=auth)
    assert created.status_code == 201, created.text
    trip = created.json()
    assert trip["title"] == TRIP_PAYLOAD["title"]
    assert len(trip["stops"]) == 2
    assert [s["order"] for s in trip["stops"]] == [1, 2]

    trip_id = trip["id"]
    fetched = await client.get(f"/api/v1/trips/{trip_id}", headers=auth)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == trip_id

    listing = await client.get("/api/v1/trips", headers=auth)
    assert listing.status_code == 200
    items = listing.json()
    assert len(items) == 1
    assert items[0]["stop_count"] == 2


async def test_share_trip_returns_link_and_public_read(client, auth):
    created = await client.post("/api/v1/trips", json=TRIP_PAYLOAD, headers=auth)
    trip_id = created.json()["id"]

    shared = await client.post(f"/api/v1/trips/{trip_id}/share", headers=auth)
    assert shared.status_code == 200
    body = shared.json()
    assert body["share_token"]
    assert body["share_url"].endswith(body["share_token"])

    # The shared itinerary is readable without authentication via the token.
    public = await client.get(f"/api/v1/trips/shared/{body['share_token']}")
    assert public.status_code == 200
    assert public.json()["id"] == trip_id


async def test_unknown_trip_is_404(client, auth):
    resp = await client.get("/api/v1/trips/does-not-exist", headers=auth)
    assert resp.status_code == 404


async def test_trip_isolation_between_users(client, auth):
    created = await client.post("/api/v1/trips", json=TRIP_PAYLOAD, headers=auth)
    trip_id = created.json()["id"]

    other = create_access_token(user_id="someone-else", subscription_tier="free")
    resp = await client.get(
        f"/api/v1/trips/{trip_id}", headers={"Authorization": f"Bearer {other}"}
    )
    assert resp.status_code == 404
