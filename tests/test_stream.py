"""Streaming chat endpoint (SSE)."""

from __future__ import annotations

import json


async def _collect_events(client, auth, body: dict) -> list[dict]:
    events: list[dict] = []
    async with client.stream("POST", "/api/v1/agent/chat/stream", json=body, headers=auth) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        buf = ""
        async for chunk in resp.aiter_text():
            buf += chunk
            frames = buf.split("\n\n")
            buf = frames.pop()
            for frame in frames:
                line = frame.strip()
                if line.startswith("data:"):
                    events.append(json.loads(line[len("data:"):].strip()))
    return events


async def test_stream_yields_done_with_conversation_id(client, auth):
    events = await _collect_events(client, auth, {"message": "hello"})
    assert events, "expected at least one SSE event"
    done = [e for e in events if e.get("type") == "done"]
    assert len(done) == 1
    assert done[0]["conversation_id"]
    assert all(e.get("type") in {"delta", "done", "error"} for e in events)


async def test_stream_requires_auth(client):
    resp = await client.post("/api/v1/agent/chat/stream", json={"message": "hi"})
    assert resp.status_code == 401


async def test_stream_continues_conversation(client, auth):
    first = await _collect_events(client, auth, {"message": "hi"})
    cid = next(e["conversation_id"] for e in first if e.get("type") == "done")
    second = await _collect_events(client, auth, {"message": "again", "conversation_id": cid})
    cid2 = next(e["conversation_id"] for e in second if e.get("type") == "done")
    assert cid2 == cid
