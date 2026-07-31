"""Agent configuration models — the core product entity."""

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class Agent(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "agents"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    voice_config: Mapped[dict] = mapped_column(JSON, default=dict)  # voice_id, speed, pitch
    platform: Mapped[str] = mapped_column(String(50), default="retell")  # retell | vapi
    # When True (Retell agents only), test calls run over our Custom LLM WebSocket
    # (DeepSeek + server-side tools, ADR-003) instead of Retell's hosted LLM. See
    # backend/services/test_call_service.py and backend/api/retell_ws.py.
    use_custom_llm: Mapped[bool] = mapped_column(Boolean, default=False)

    tenant: Mapped["Tenant"] = relationship(back_populates="agents")  # noqa: F821
    phone_numbers: Mapped[list["PhoneNumber"]] = relationship(back_populates="agent")
    tool_configs: Mapped[list["ToolConfig"]] = relationship(back_populates="agent")


class PhoneNumber(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "phone_numbers"

    agent_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"))
    number: Mapped[str] = mapped_column(String(20), unique=True)
    provider: Mapped[str] = mapped_column(String(50), default="twilio")

    agent: Mapped["Agent"] = relationship(back_populates="phone_numbers")


class ToolConfig(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "tool_configs"

    agent_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"))
    tool_type: Mapped[str] = mapped_column(String(100))  # book_appointment, lookup_customer, etc
    config: Mapped[dict] = mapped_column(JSON, default=dict)

    agent: Mapped["Agent"] = relationship(back_populates="tool_configs")
