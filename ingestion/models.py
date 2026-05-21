from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Session(BaseModel):
    conversation_id: UUID
    message_id: UUID | None = None
    user_id: str = "anonymous"


class Request(BaseModel):
    input_preview: str | None = None
    input_chars: int = 0
    num_messages: int = 0
    params: dict = Field(default_factory=dict)


class Response(BaseModel):
    output_preview: str | None = None
    output_chars: int = 0
    finish_reason: str | None = None


class Usage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class Timing(BaseModel):
    started_at: datetime
    ended_at: datetime
    latency_ms: int
    ttft_ms: int | None = None


class InferenceEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")  # forward-compat: unknown fields are silently dropped

    event_id: UUID
    schema_version: int
    timestamp: datetime
    session: Session
    provider: str
    model: str
    request: Request
    response: Response
    usage: Usage
    timing: Timing
    status: Literal["success", "error", "cancelled", "timeout"]
    error: str | None = None


class IngestBatch(BaseModel):
    events: list[InferenceEvent]


class IngestResponse(BaseModel):
    accepted: int
    rejected: int = 0
    errors: list[dict] = Field(default_factory=list)
