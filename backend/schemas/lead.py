"""Pydantic schemas for the lead retry scheduler (ADR-011)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class LeadCreate(BaseModel):
    phone: str
    contact_name: str | None = None
    business_name: str | None = None
    email: str | None = None
    city: str | None = None
    country: str | None = None
    timezone: str | None = None  # IANA name; falls back to settings.default_lead_timezone

    source: str = "bark"
    bark_request_id: str | None = None
    service_requested: str | None = None
    budget: str | None = None
    request_text: str | None = None
    received_at: datetime | None = None
    details: dict = Field(default_factory=dict)

    notes: str | None = None
    agent_id: uuid.UUID | None = None


class LeadUpdate(BaseModel):
    """Every field optional; the router applies whatever was actually set
    (model_fields_set), so an explicit null clears a nullable field rather than being
    read as "not supplied" — same convention as ProspectUpdate.
    """

    contact_name: str | None = None
    business_name: str | None = None
    phone: str | None = None
    email: str | None = None
    city: str | None = None
    country: str | None = None
    timezone: str | None = None

    service_requested: str | None = None
    budget: str | None = None
    request_text: str | None = None
    details: dict | None = None

    notes: str | None = None
    agent_id: uuid.UUID | None = None
    status: str | None = None  # new | contacted | booked | not_interested | unreachable


class LeadResponse(BaseModel):
    id: uuid.UUID
    contact_name: str | None
    business_name: str | None
    phone: str
    email: str | None
    city: str | None
    country: str | None
    timezone: str | None

    source: str
    bark_request_id: str | None
    service_requested: str | None
    budget: str | None
    request_text: str | None
    received_at: datetime | None
    details: dict

    notes: str | None
    agent_id: uuid.UUID | None

    retry_state: str
    attempt_count: int
    next_attempt_at: datetime | None
    last_attempt_at: datetime | None
    last_outcome: str | None

    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class LeadStats(BaseModel):
    total: int = 0
    paused: int = 0
    scheduled: int = 0
    in_flight: int = 0
    succeeded: int = 0
    exhausted: int = 0
    do_not_call: int = 0


class LeadCallRequest(BaseModel):
    """Dial a lead right now, outside the schedule. Both optional — default to the
    lead's own agent_id/phone, same override convention as ProspectCallRequest.
    """

    agent_id: uuid.UUID | None = None
    to_number: str | None = None
