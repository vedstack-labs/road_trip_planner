"""Agent chat schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(
        default=None,
        description="Opaque id to continue a prior conversation; a new one is minted if omitted.",
    )


class ChatResponse(BaseModel):
    conversation_id: str = Field(serialization_alias="conversationId")
    response: str

    model_config = {"populate_by_name": True}
