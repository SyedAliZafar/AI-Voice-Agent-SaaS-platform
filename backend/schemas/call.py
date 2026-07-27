"""Pydantic schemas for call history and transcripts."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class CallResponse(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    caller_number: str
    status: str
    duration_sec: int
    sentiment_score: float | None
    started_at: datetime

    model_config = {"from_attributes": True}


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
