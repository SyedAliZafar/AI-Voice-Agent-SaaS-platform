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
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    source_query: Mapped[str] = mapped_column(String(255), default="")

    # Research (Agent 2 — the knowledge base)
    research_status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending | running | ready | failed
    research: Mapped[dict] = mapped_column(JSON, default=dict)  # CompanyResearch shape
    research_error: Mapped[str | None] = mapped_column(Text, nullable=True)

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
