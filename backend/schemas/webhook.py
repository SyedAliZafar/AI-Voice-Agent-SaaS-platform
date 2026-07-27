"""Schemas for incoming voice platform webhook payloads.

These are intentionally loose (extra='allow') because Retell/Vapi payload
shapes evolve — validate only the fields we actually branch on.
"""

from pydantic import BaseModel, ConfigDict


class RetellWebhookEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    event: str  # call_started | call_ended | transcript_update
    call_id: str
    transcript: str | None = None


class VapiWebhookEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    call: dict
