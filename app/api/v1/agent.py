"""Agent chat endpoints. Never publicly accessible — require a valid JWT."""

from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.agent.planner_agent import run_chat, run_chat_stream
from app.auth.deps import CurrentPrincipal, CurrentUser, DbSession, load_or_provision_user
from app.db.base import get_sessionmaker
from app.schemas.agent import ChatRequest, ChatResponse

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/chat", response_model=ChatResponse, response_model_by_alias=True)
async def chat(
    body: ChatRequest,
    user: CurrentUser,
    principal: CurrentPrincipal,
    session: DbSession,
) -> ChatResponse:
    conversation_id, response = await run_chat(
        session,
        user=user,
        principal=principal,
        message=body.message,
        conversation_id=body.conversation_id,
    )
    return ChatResponse(conversation_id=conversation_id, response=response)


@router.post("/chat/stream")
async def chat_stream(body: ChatRequest, principal: CurrentPrincipal) -> StreamingResponse:
    """Server-sent events: incremental text, then a final event with the
    conversation id. Each event is ``data: {json}\\n\\n``.

    Uses its own DB session inside the generator because the streaming body runs
    after the request handler returns (the request-scoped session would be closed).
    """

    async def event_stream():
        async with get_sessionmaker()() as session:
            try:
                user = await load_or_provision_user(session, principal)
                async for event in run_chat_stream(
                    session,
                    user=user,
                    principal=principal,
                    message=body.message,
                    conversation_id=body.conversation_id,
                ):
                    yield f"data: {json.dumps(event)}\n\n"
            except Exception as exc:  # surface a clean error event to the client
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
