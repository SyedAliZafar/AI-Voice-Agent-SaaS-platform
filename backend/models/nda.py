"""NdaDispatch model — one NDA sent (or pending) for one lead call (phase5 Session 3).

**Why this table exists at all, rather than a couple of columns on Lead.** The record is
the idempotency guarantee. ADR-009 established a connection-scoped ledger in
`api/retell_ws.py` that stops a barge-in from double-firing a side-effecting tool, and
that mechanism is genuinely load-bearing for bookings — but it lives in a Python set on a
websocket handler, so it dies with the connection. Nothing in it can stop a retried Celery
task, a second `call_analyzed` webhook, or a reconcile from sending a second copy of a
legal document. That needs a database constraint, which needs a row:

    UniqueConstraint(lead_id, call_id)

One NDA per lead per call. An operator resend bumps `attempt_count` on the existing row
rather than inserting a second one, so "how many times did we send this" stays answerable.
The same row doubles as the audit trail and the operator's review surface, which is why it
carries the extraction evidence (`extraction_quote`, `extraction_confidence`) and not just
the outcome.

**Deliberately NOT denormalized onto Lead.** No `Lead.nda_state` column: read it through
the relationship. ADR-006's "two overlapping outreach axes" note documents what happens
when one fact gets two homes — `Prospect.status` and `Prospect.outreach_status` drifted
into disagreement by accretion, and "have we called them" now has two answers. Not
repeating that here.

**The state machine**, and why it starts where it does:

    pending_review -> queued -> sending -> sent -> viewed -> signed
                                                        `-> declined
    (any) -> failed
    blocked (terminal until an operator supplies an email)

`pending_review` is the entry state because the send gate is post-call extraction plus
human confirmation, not a mid-call tool call. That wasn't the first choice: the natural
design is a `send_nda` tool the agent invokes when the lead agrees, and it is currently
impossible — lead calls are forced onto Retell's hosted-LLM path (test_call_service's
`_provision_custom_llm_agent` rejects `system_prompt_override`), where `retell_ws.py`
never runs and therefore no `backend/tools/` handler can execute. See
phases/in-progress/phase5.md, "The rejected mid-call gate", before changing this.

`sending` is not redundant with `queued`. It means "we made the provider request and never
saw a response" — the ambiguous state `IntegrationTimeoutError` exists to represent
(integration_service). A row here must NOT be retried blind, because a blind retry of a
send that actually landed puts a second NDA in someone's inbox; it gets settled by asking
the provider, the same way ADR-007 settles a missing webhook by asking Retell.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TenantMixin, TimestampMixin, UUIDMixin

# The full set of valid `state` values. A module constant rather than a DB enum for the
# same reason lead.retry_state is a plain string: adding a state shouldn't need a
# migration, and every existing status axis in this codebase (Call.status,
# Lead.retry_state, Prospect.outreach_status) is already a validated string.
NDA_STATES = (
    "pending_review",  # extraction proposed a recipient; a human hasn't confirmed
    "blocked",  # lead agreed but we have no usable email — needs an operator
    "queued",  # approved, waiting for the worker
    "sending",  # request made, no response seen — AMBIGUOUS, never retry blind
    "sent",  # provider accepted it
    "viewed",  # recipient opened it
    "signed",  # executed
    "declined",  # recipient refused
    "failed",  # provider rejected it outright
)

# States where nothing further will happen without a human. Used by the operator UI and
# by the reconcile sweep to decide what's worth re-checking.
NDA_TERMINAL_STATES = ("signed", "declined", "failed", "blocked")


class NdaDispatch(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "nda_dispatches"
    __table_args__ = (
        # The whole point of the table — see the module docstring. Without this, an
        # at-least-once Celery delivery is an at-least-once legal document.
        UniqueConstraint("lead_id", "call_id", name="uq_nda_dispatches_lead_call"),
    )

    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id"), nullable=False, index=True
    )
    # Which call produced the agreement. Part of the uniqueness key rather than just
    # provenance: a lead called again next quarter for a different engagement should be
    # able to receive a new NDA, and keying on lead_id alone would silently block that.
    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id"), nullable=False
    )

    # Where it goes. Nullable because "agreed but we couldn't get an address" is a real
    # outcome that must be visible (state="blocked") rather than dropped — Lead.email is
    # itself nullable and Bark doesn't always supply one.
    recipient_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recipient_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    state: Mapped[str] = mapped_column(String(20), default="pending_review", index=True)

    # Evidence for the human doing the review. The quote is what makes an approve/reject
    # decision take five seconds instead of reading a whole transcript, and it's the only
    # way to audit an extraction that got it wrong after the fact.
    extraction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    extraction_quote: Mapped[str | None] = mapped_column(Text, nullable=True)

    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # The provider's own id for the signature request — how the webhook (Session 5) finds
    # this row, and how the reconcile path settles a "sending" row.
    provider_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    # Counts real send attempts, including operator resends. Not a retry budget for the
    # ambiguous "sending" state, which is settled by asking the provider, never by
    # retrying.
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    # The provider's own error text, same principle as
    # integration_service._raise_for_status_with_body: a bare status code helps nobody.
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    signed_document_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
