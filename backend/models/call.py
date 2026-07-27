"""Call lifecycle models — calls, their events, and transcripts."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class Call(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "calls"

    agent_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"))
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
