"""Prospect model — companies discovered via Google Places (or CSV import), ranked
for outreach.

Three independent status axes:
  research_status: pending -> running -> ready | failed  (has the KB been built?)
  outreach_status: not_reached -> reached | callback | do_not_call  (have we called them?)
  status:          not_called | called | booked | flagged | no_answer | do_not_call
                   (what was the *outcome* of working this prospect?)

`status` and `outreach_status` overlap and are deliberately NOT auto-synced — see the
"two overlapping outreach axes" note in CONTEXT.md ADR-006. `outreach_status` is the
Places-pipeline axis that `record_call()` advances automatically; `status` is the
operator-set campaign-outcome axis behind the /prospects dropdown and counts strip.
Reconciling them into one field is an open design decision, not an oversight.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class Prospect(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "prospects"

    # Identity (from Google Places)
    google_place_id: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # city/country are structured fields sourced from Google Places' addressComponents
    # (places_service._normalize), NOT parsed out of `address` — formatted-address
    # strings order components differently across countries (a "second-to-last comma
    # segment" heuristic breaks even within the UK: "Bristol, Clevedon BS21 6RR" has
    # Clevedon as the town and Bristol as the postal county). CSV imports populate city
    # directly from their own city/country columns (operator-typed and unvalidated,
    # unlike the Places path's canonical addressComponents value — near-duplicate
    # spellings like "UK" vs "United Kingdom" will group separately in the UI). No
    # index yet — same as `category`, which has the same shape and isn't indexed
    # either; add one if/when grouping/filtering queries actually need it.
    city: Mapped[str | None] = mapped_column(String(255), nullable=True)
    country: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    source_query: Mapped[str] = mapped_column(String(255), default="")
    # The `location` half of the discovery search that found this row ("Bristol, UK").
    # Sibling to source_query rather than folded into it: they answer different
    # questions (*what* was searched vs. *where*), and joining them into one string
    # would make either one unfilterable on its own. Set once at creation and never
    # updated, exactly like source_query. Null for CSV imports and for rows discovered
    # before this column existed.
    source_location: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Research (Agent 2 — the knowledge base)
    research_status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending | running | ready | failed
    research: Mapped[dict] = mapped_column(JSON, default=dict)  # CompanyResearch shape
    research_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Operator-written context, injected alongside `research` into the call prompt
    # (script_service.build_prospect_prompt). Distinct from `research`: that is machine-
    # generated and clobbered wholesale on every re-run, this survives one.
    prospect_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Outreach tracking
    outreach_status: Mapped[str] = mapped_column(String(20), default="not_reached")
    # not_reached | reached | callback | do_not_call
    status: Mapped[str] = mapped_column(String(20), default="not_called", index=True)
    # not_called | called | booked | flagged | no_answer | do_not_call
    # Indexed because /prospects/stats aggregates on it on every page load.
    last_called_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    call_count: Mapped[int] = mapped_column(Integer, default=0)

    # Ranking (Agent 1 — who to reach first)
    priority_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
