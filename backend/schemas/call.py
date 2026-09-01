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
    # Null when the call was placed through a platform-native agent (ADR-012) — those
    # have no local Agent row, and carry external_agent_id instead. Exactly one of the
    # two is set on any given call.
    agent_id: uuid.UUID | None
    external_agent_id: str | None = None
    caller_number: str
    status: CallStatus
    duration_sec: int
    sentiment_score: float | None
    started_at: datetime
    # Set when the call was placed to work a Prospect (per-prospect /call or a batch run).
    prospect_id: uuid.UUID | None = None
    # Retell's raw disconnection_reason, kept verbatim next to the coarser `status` —
    # "voicemail_reached", "dial_no_answer", "user_hangup", … Null until terminal.
    disconnection_reason: str | None = None
    # True/False once terminal (did a person speak), None while in progress or unknown.
    answered_by_human: bool | None = None

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


class CallEventResponse(BaseModel):
    """One row of a call's server-side audit trail (models/call.py's CallEvent).

    `payload` is deliberately an untyped dict: each event_type carries its own shape —
    "tool_call" holds {phase, tool, arguments|result|error}, "llm_timing" holds
    {stage, model, duration_ms, ttfb_ms, ...}, "ivr_hangup" holds the detector's
    evidence. Declaring a union of those here would restate, in a second place, shapes
    whose authority lives at the writer (call_service.record_tool_event /
    record_llm_events / record_call_event) — and the reader is a timeline that renders
    whatever it's given, not a consumer that branches on every key.
    """

    id: uuid.UUID
    event_type: str
    payload: dict
    ts: datetime

    model_config = {"from_attributes": True}
