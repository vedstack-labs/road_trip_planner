"""Auth guarding: the agent is never publicly accessible."""

from __future__ import annotations

import pytest

from app.auth.jwt import AuthError, create_access_token, decode_token


async def test_chat_requires_bearer_token(client):
    resp = await client.post("/api/v1/agent/chat", json={"message": "hi"})
    assert resp.status_code == 401


async def test_invalid_token_rejected(client):
    resp = await client.post(
        "/api/v1/agent/chat",
        json={"message": "hi"},
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert resp.status_code == 401


async def test_trips_require_auth(client):
    assert (await client.get("/api/v1/trips")).status_code == 401


def test_token_roundtrip_carries_claims():
    tok = create_access_token(
        user_id="u1", vehicle_id="v9", subscription_tier="premium", roles=["driver"]
    )
    p = decode_token(tok)
    assert p.user_id == "u1"
    assert p.vehicle_id == "v9"
    assert p.subscription_tier == "premium"
    assert p.roles == ["driver"]


def test_tampered_token_raises():
    tok = create_access_token(user_id="u1")
    with pytest.raises(AuthError):
        decode_token(tok + "tamper")


async def test_dev_token_endpoint_issues_usable_token(client):
    resp = await client.post("/api/v1/auth/dev-token", json={"user_id": "u-dev"})
    assert resp.status_code == 200
    tok = resp.json()["access_token"]
    # The issued token authenticates a real request.
    me = await client.get("/api/v1/trips", headers={"Authorization": f"Bearer {tok}"})
    assert me.status_code == 200
