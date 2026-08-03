"""Pydantic schemas for call history and transcripts."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

# The full set of Call.status values, all written by call_service. Declared as a Literal
# rather than a bare `str` so the API contract matches what the frontend already assumes
# in lib/types.ts — that mismatch was real drift, with the frontend the stricter side.
CallStatus = Literal["in_progress", "resolved", "escalated", "failed"]


class CallResponse(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    caller_number: str
    status: CallStatus
    duration_sec: int
    sentiment_score: float | None
    started_at: datetime

    model_config = {"from_attributes": True}


class CallSyncResponse(BaseModel):
    """Result of POST /api/calls/sync — how many stranded calls got repaired."""

    updated: int


class TranscriptTurn(BaseModel):
    role: str  # caller | agent
    text: str
    ts: datetime


class TranscriptResponse(BaseModel):
    call_id: uuid.UUID
    full_text: str
    turns: list[TranscriptTurn]
    s3_audio_url: str | None

    model_config = {"from_attributes": True}
