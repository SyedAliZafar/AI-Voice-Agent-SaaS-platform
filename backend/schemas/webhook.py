"""Schemas for incoming voice platform webhook payloads.

These are intentionally loose (extra='allow') because Retell/Vapi payload
shapes evolve — validate only the fields we actually branch on.

Retell nests everything under a "call" object:

    {"event": "call_ended", "call": {"call_id": "...", "duration_ms": 12345, ...}}

An earlier version of this file expected `call_id` at the TOP level, which meant every
real Retell webhook 422'd before reaching a handler — so calls were never marked ended
and sat at status="in_progress" forever. Keep `call_id` sourced from the nested object.

Retell sends exactly three webhook events: call_started, call_ended, call_analyzed.
There is no transcript_update webhook — that's a *websocket* concept from the custom-LLM
protocol (backend/api/retell_ws.py), not a webhook. Transcripts arrive on the
call_ended/call_analyzed payloads instead.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict


class RetellWebhookEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    event: str  # call_started | call_ended | call_analyzed
    call: dict[str, Any]

    @property
    def call_id(self) -> str:
        return str(self.call.get("call_id") or "")

    @property
    def transcript(self) -> str | None:
        value = self.call.get("transcript")
        return value if isinstance(value, str) else None


class VapiWebhookEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    call: dict
