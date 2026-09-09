"""Batch outreach run models — serial, event-chained dialing of a small prospect list.

A BatchRun replaces the "for prospect in targets: dial" loop in the old POST
/prospects/batch-call (kept for one-shot fire-everything use) with a run that dials
exactly one prospect at a time and advances only when the previous call reaches a
terminal state (call_service._fanout_post_call), not on a fixed timer. See
phases/in-progress/serial-batch-calling.md for the design rationale.

Two tables rather than a JSON id-list + cursor on one row: a real row per prospect
gives batch_service.claim_next() a single conditional UPDATE to claim the next target
(the concurrency-safety this whole design rests on — _fanout_post_call runs more than
once per call by contract), and gives the run-progress UI per-item status/skip-reason
for free instead of reconstructing it from call rows.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class BatchRun(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "batch_runs"

    # Same agent-source rule as Call/ProspectCallRequest: exactly one of the two names
    # who makes every call in this run (enforced in batch_service, not the column).
    agent_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True
    )
    external_agent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    # running | done | cancelled | failed

    # Platform-agent path only — applied to every call in the run, same as
    # BatchCallRequest.dynamic_variables. Empty dict for the local-agent path.
    dynamic_variables: Mapped[dict] = mapped_column(JSON, default=dict)

    total: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list["BatchRunItem"]] = relationship(
        back_populates="run", order_by="BatchRunItem.position"
    )


class BatchRunItem(Base, UUIDMixin, TimestampMixin):
    """One prospect's slot in a BatchRun. `position` fixes dial order (the same
    priority_score ordering batch_call_targets already applies); `status` is the state
    claim_next() advances with a single conditional UPDATE so a call whose terminal
    webhook fires twice (call_ended + call_analyzed, or a later reconcile — see
    call_service._fanout_post_call's docstring) can only ever dial the next prospect once.
    """

    __tablename__ = "batch_run_items"

    run_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batch_runs.id"), index=True
    )
    prospect_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prospects.id"))
    position: Mapped[int] = mapped_column(Integer)

    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    # queued | dialing | done | skipped

    call_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id"), nullable=True
    )
    skip_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dialed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped["BatchRun"] = relationship(back_populates="items")
