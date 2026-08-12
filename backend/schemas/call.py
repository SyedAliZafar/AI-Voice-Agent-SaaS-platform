"""Pydantic schemas for call history and transcripts."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, computed_field

from backend.config import get_settings

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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cost_usd(self) -> float:
        """Flat estimate at settings.call_cost_per_minute — not itemized against the
        voice platform's/LLM provider's actual bills, just duration * rate. Still 0 for
        an in_progress call since duration_sec isn't final yet; the frontend re-fetches
        once the call resolves, same as every other field here."""
        return round((self.duration_sec / 60) * get_settings().call_cost_per_minute, 4)


class CallSyncResponse(BaseModel):
    """Result of POST /api/calls/sync — how many stranded calls got repaired."""

    updated: int


class TranscriptTurn(BaseModel):
    role: Literal["caller", "agent"]
    text: str
    ts: datetime


class TranscriptResponse(BaseModel):
    call_id: uuid.UUID
    full_text: str
    turns: list[TranscriptTurn]
    s3_audio_url: str | None

    model_config = {"from_attributes": True}
