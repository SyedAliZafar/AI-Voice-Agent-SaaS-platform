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

    # Of the `imported` rows, how many carry a website. Research quality hinges on this:
    # research_service scrapes the website and falls back to name/address-only ("degraded")
    # research when it's absent, so the operator should see the split at upload time
    # rather than discovering it later in thin CompanyResearch briefs.
    with_website: int = 0
    without_website: int = 0

    # Ids of the rows just created, for the caller to enqueue research on. Excluded from
    # the HTTP response — this is an internal handoff between import_from_csv() and the
    # endpoint, not part of the operator-facing report.
    imported_ids: list[uuid.UUID] = Field(default_factory=list, exclude=True)


class ProspectStats(BaseModel):
    """Per-status row counts for the /prospects counts strip. Every field defaults to 0
    so a status with no rows still renders as a number rather than a gap.
    """

    total: int = 0
    not_called: int = 0
    called: int = 0
    booked: int = 0
    flagged: int = 0
    no_answer: int = 0
    do_not_call: int = 0


class ProspectCallRequest(BaseModel):
    agent_id: uuid.UUID
    to_number: str | None = None  # defaults to the prospect's stored phone if omitted
