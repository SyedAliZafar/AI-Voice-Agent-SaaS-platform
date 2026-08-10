"""Pydantic schemas for prospect discovery, research, and outreach."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CompanyResearch(BaseModel):
    """The knowledge base distilled for one company. Consumed by
    script_service.build_prospect_prompt() to personalize a campaign script.
    """

    summary: str = ""
    industry: str = ""
    size_hint: str = ""
    pain_points: list[str] = Field(default_factory=list)
    hooks: list[str] = Field(default_factory=list)  # concrete opening-line angles
    talking_points: list[str] = Field(default_factory=list)
    do_not_mention: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class DiscoverRequest(BaseModel):
    query: str  # e.g. "dentists in Berlin"
    location: str | None = None  # optional bias, e.g. "Berlin, Germany"
    radius_m: int = 20_000
    limit: int = 20


class ProspectResponse(BaseModel):
    id: uuid.UUID
    google_place_id: str
    name: str
    website: str | None
    phone: str | None
    address: str | None
    category: str | None
    rating: float | None
    review_count: int
    source_query: str

    research_status: str
    research: CompanyResearch
    research_error: str | None

    outreach_status: str
    status: str
    last_called_at: datetime | None
    call_count: int

    priority_score: float
    created_at: datetime

    model_config = {"from_attributes": True}


class ProspectUpdate(BaseModel):
    outreach_status: str | None = None  # not_reached | reached | callback | do_not_call
    status: str | None = None
    # not_called | called | booked | flagged | no_answer | do_not_call


class CsvImportResult(BaseModel):
    """Outcome of one CSV upload. Deliberately a report, not an exception: a file with
    some bad rows still imports the good ones, and the operator sees why the rest fell out.
    """

    imported: int = 0
    skipped_duplicates: int = 0  # phone already on a prospect for this tenant, or repeated in-file
    skipped_invalid: int = 0  # unusable phone or missing business_name
    errors: list[str] = Field(default_factory=list)  # per-row reasons, truncated


class ProspectCallRequest(BaseModel):
    agent_id: uuid.UUID
    to_number: str | None = None  # defaults to the prospect's stored phone if omitted
