"""Lead model — warm inbound leads (Bark.com and other sources) the operator enters by
hand, with an automatic call-retry scheduler (ADR-011).

Two independent status axes, same shape as Prospect (see CONTEXT.md ADR-006's "two
overlapping outreach axes" note) but kept deliberately separate here from day one:

  retry_state: paused -> scheduled -> in_flight -> succeeded | exhausted
                                 `-> do_not_call (terminal, from any state)
               Drives the scheduler: only `scheduled` rows with a due `next_attempt_at`
               get dialed. Set by lead_service, never directly by the operator except
               via start/pause/do-not-call actions.

  status: new | contacted | booked | not_interested | unreachable
          Operator-facing outcome, same idea as Prospect.status — what came of this
          lead, independent of whether the scheduler is still trying.

Fields are deliberately generic (source, details JSON, notes) rather than modeling
Bark's exact API shape, since no real Bark payload has been seen yet — see the
"columns we will add or remove later" note in CONTEXT.md ADR-011.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class Lead(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "leads"

    # Identity — typed in by the operator, not scraped.
    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    business_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(255), nullable=True)
    country: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # IANA tz name (e.g. "Europe/London"). Null falls back to
    # settings.default_lead_timezone at scheduling time — see lead_service._resolve_tz.
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Where this lead came from, and whatever came with it. Generic on purpose: no real
    # Bark payload has been mapped yet, so this is a catch-all rather than a guessed
    # column-per-field. service_requested/budget/request_text are pulled out because
    # they read naturally in the call prompt; anything else goes in `details`.
    source: Mapped[str] = mapped_column(String(50), default="bark")
    bark_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    service_requested: Mapped[str | None] = mapped_column(String(255), nullable=True)
    budget: Mapped[str | None] = mapped_column(String(100), nullable=True)
    request_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)

    # Operator's own hand-written context — the per-lead "holder". Injected into the
    # call prompt after everything else and described to the model as authoritative,
    # same convention as Prospect.prospect_notes.
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Which agent calls this lead. Required before the lead can be started — enforced
    # in lead_service, not at the column level, so a lead can be entered before an
    # agent is decided.
    agent_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True
    )

    # Retry scheduler state (ADR-011).
    retry_state: Mapped[str] = mapped_column(String(20), default="paused", index=True)
    # paused | scheduled | in_flight | succeeded | exhausted | do_not_call
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Raw outcome of the most recent attempt (a Call.status value, or "dispatch_error: ...").
    # Diagnostic only — retry_state is what the scheduler actually acts on.
    last_outcome: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Operator-facing campaign-outcome axis — see module docstring.
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    # new | contacted | booked | not_interested | unreachable
