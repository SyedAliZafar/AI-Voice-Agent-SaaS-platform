"""Call lifecycle models — calls, their events, and transcripts."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class Call(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "calls"

    # Nullable because not every call is placed by an Agent row we own: a call dialed
    # through an agent built in the voice platform's own dashboard (ADR-012) has no
    # local Agent to point at, and carries external_agent_id instead. Exactly one of
    # the two is set — see call_service.create_outbound_call_record.
    agent_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True
    )
    # The voice platform's own agent id (e.g. Retell's "agent_xxx") when this call was
    # placed through a platform-native agent we don't manage (ADR-012). Null for every
    # call originated from a local Agent row, which is the normal path.
    external_agent_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    caller_number: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(50), default="in_progress")
    # in_progress | resolved | escalated | failed
    duration_sec: Mapped[int] = mapped_column(Integer, default=0)
    sentiment_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Voice platform's own call ID (Retell/Vapi) — lets webhook handlers correlate
    # an inbound event back to this row. Set at call_service.create_outbound_call_record()
    # time for calls we originate; nullable because inbound-webhook-first call creation
    # isn't wired up yet (see call_service.py module docstring).
    external_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True, nullable=True
    )
    # Set only for calls placed by the lead retry scheduler (ADR-011) — lets
    # call_service's terminal-state writer (apply_retell_call_state) hand off to
    # lead_service.evaluate_call_outcome without every other call path knowing leads
    # exist. Null for ordinary test calls and prospect calls.
    lead_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id"), nullable=True, index=True
    )
    # Per-call personalized script (base campaign script + [COMPANY BRIEF]/[OPERATOR
    # NOTES], built by script_service.build_prospect_prompt) for use_custom_llm agents.
    # The hosted-LLM path pushes its override straight to Retell at provisioning time and
    # never needs this; our own Custom LLM websocket (backend/api/retell_ws.py) has no
    # other channel to receive a call-scoped prompt — Retell's frames carry only call_id —
    # so the override rides on the Call row it already looks up by external_id.
    # Null for plain test calls and lead-retry calls, which use Agent.system_prompt as-is.
    system_prompt_override: Mapped[str | None] = mapped_column(Text, nullable=True)

    events: Mapped[list["CallEvent"]] = relationship(back_populates="call")
    transcript: Mapped["Transcript"] = relationship(back_populates="call", uselist=False)


class CallEvent(Base, UUIDMixin):
    __tablename__ = "call_events"

    call_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("calls.id"))
    event_type: Mapped[str] = mapped_column(String(100))  # tool_call, transfer, hangup, error
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    call: Mapped["Call"] = relationship(back_populates="events")


class Transcript(Base, UUIDMixin):
    __tablename__ = "transcripts"

    call_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("calls.id"), unique=True)
    full_text: Mapped[str] = mapped_column(Text, default="")
    turns: Mapped[list] = mapped_column(JSON, default=list)  # [{role, text, ts}, ...]
    s3_audio_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    call: Mapped["Call"] = relationship(back_populates="transcript")
