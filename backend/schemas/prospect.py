"""Pydantic schemas for prospect discovery, research, and outreach."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.schemas.agent import SandboxMessage, _validate_llm_model


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
    # Structured fields sourced from Google Places' addressComponents, not parsed out of
    # `address` — see backend/models/prospect.py. Null for rows discovered/imported
    # before this existed, and for CSV rows (country has no CSV column yet).
    city: str | None
    country: str | None
    category: str | None
    rating: float | None
    review_count: int
    source_query: str
    source_location: str | None

    research_status: str
    research: CompanyResearch
    research_error: str | None
    prospect_notes: str | None

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

    # None is a real value here (clear the notes), so the router keys off
    # model_fields_set rather than truthiness to tell "clear" from "not supplied".
    prospect_notes: str | None = None


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
    voicemail: int = 0
    do_not_call: int = 0


class SheetSyncResult(BaseModel):
    """What POST /api/prospects/sync-sheet did — one pull-then-push round trip.

    `rows_read` is what the sheet held; `written` is what it holds now (prospects the
    sheet didn't have, from discovery or a CSV import, get appended). `queued` counts
    rows whose "Call again?" box was ticked and are now eligible for the next batch call.
    """

    rows_read: int = 0
    created: int = 0
    updated: int = 0
    queued: int = 0
    written: int = 0


class CallSyncResult(BaseModel):
    """What POST /api/prospects/sync-calls did — the operator's receipt for a backfill.

    `matched` / `unmatched` split the fetched calls by whether a prospect's phone number
    lined up, which is the number to look at when a sync "did nothing": a high unmatched
    count usually means the list was never imported, not that the sync is broken.
    """

    fetched: int = 0
    created: int = 0
    updated: int = 0
    matched: int = 0
    unmatched: int = 0


class CityAutocompleteResult(BaseModel):
    place_id: str
    label: str  # e.g. "Bristol, United Kingdom" — shown verbatim in the suggestion list


class CityAutocompleteResponse(BaseModel):
    suggestions: list[CityAutocompleteResult]


class ProspectCallRequest(BaseModel):
    """Exactly one of agent_id / external_agent_id names who makes the call.

    They are not interchangeable, and the difference is the whole point of this page:
    a local agent gets this prospect's researched [COMPANY BRIEF] + [OPERATOR NOTES]
    injected into its script for this one call, while a platform-native agent (ADR-012)
    holds its own script in the platform's dashboard and cannot receive any of it. The
    knowledge base above the call form applies to the first and is silently irrelevant
    to the second — which is why the UI labels the choice rather than blending them.
    """

    agent_id: uuid.UUID | None = None
    external_agent_id: str | None = None
    to_number: str | None = None  # defaults to the prospect's stored phone if omitted
    # Platform-agent path only: fills the dashboard prompt's {{placeholders}} for this
    # call (ADR-012). This is how a platform agent gets personalized at all — it can't
    # receive a rewritten prompt, but it can be told who it's calling. Ignored on the
    # local-agent path, which injects the full brief instead.
    dynamic_variables: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _exactly_one_agent(self) -> "ProspectCallRequest":
        if (self.agent_id is None) == (self.external_agent_id is None):
            raise ValueError("provide exactly one of agent_id or external_agent_id")
        return self


class BatchCallRequest(BaseModel):
    """Dial a batch of not-yet-called prospects with one agent.

    Same agent-source rule as ProspectCallRequest: exactly one of agent_id /
    external_agent_id. The local-agent path only dials prospects whose research is
    "ready" (it needs the [COMPANY BRIEF]); anything not ready is reported as skipped
    rather than failing the run. The platform-agent path has no such gate.
    """

    agent_id: uuid.UUID | None = None
    external_agent_id: str | None = None
    limit: int = Field(default=10, ge=1, le=50)
    city: str | None = None  # restrict the batch to one city
    # Prospects called at most this many times are eligible — 0 (default) means "never
    # called". Raise it to re-work no-answers.
    max_call_count: int = Field(default=0, ge=0)
    # Platform-agent path only — fills the dashboard prompt's {{placeholders}}, applied
    # to every call in the batch (per-prospect personalization is the local-agent path).
    dynamic_variables: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _exactly_one_agent(self) -> "BatchCallRequest":
        if (self.agent_id is None) == (self.external_agent_id is None):
            raise ValueError("provide exactly one of agent_id or external_agent_id")
        return self


class BatchCallDispatch(BaseModel):
    prospect_id: uuid.UUID
    name: str
    call_id: str


class BatchCallSkip(BaseModel):
    prospect_id: uuid.UUID
    name: str
    reason: str


class BatchCallResult(BaseModel):
    requested: int  # how many eligible prospects the filter matched (<= limit)
    dispatched: list[BatchCallDispatch] = Field(default_factory=list)
    skipped: list[BatchCallSkip] = Field(default_factory=list)


class ProspectSandboxChatRequest(BaseModel):
    """Text-chat sandbox for one prospect's personalized script. Reuses SandboxMessage
    from schemas.agent rather than redefining it — same shape, one type.

    tools_enabled is deliberately NOT exposed here (unlike the agent-level sandbox,
    which lets the operator opt in): book_appointment/create_lead firing real HTTP
    calls against a *specific real prospect's* calendar/CRM while the operator is only
    testing a pitch is a worse accident than the generic agent sandbox risks.
    """

    agent_id: uuid.UUID
    messages: list[SandboxMessage] = Field(min_length=1, max_length=50)
    model: str | None = None

    @field_validator("model")
    @classmethod
    def _validate_model(cls, value: str | None) -> str | None:
        if value:
            return _validate_llm_model(value)
        return value
