"""Tenant and User models — the multi-tenancy root."""

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class Tenant(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    plan: Mapped[str] = mapped_column(String(50), default="trial")

    # --- NDA party data (phase5 Session 3) -------------------------------------------
    # Merge fields for the platform-owned NDA template. These live on Tenant, not on
    # Integration, because we supply the document and send it from our own Dropbox Sign
    # account — there is no per-tenant e-sign credential to hang them off. What varies
    # per tenant is only who the agreement names as the disclosing party.
    #
    # `name` above is the display name ("Acme"); this is the legal entity ("Acme Digital
    # Ltd."). Deliberately a separate column rather than reusing it: an NDA naming the
    # wrong entity is not enforceable, and the display name is edited freely by the UI.
    nda_company_legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nda_signer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nda_signer_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nda_signer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Off by default, deliberately: post-call extraction proposes a recipient and a human
    # confirms it (state="pending_review"). Flipping this on lets a high-confidence
    # extraction send without review. The point of the default is to watch the extractor
    # be right across real calls first — the top failure mode of this whole feature is an
    # email address heard over a phone line, and the cost of getting it wrong is a legal
    # document delivered to a stranger. See phases/in-progress/phase5.md Session 4.
    nda_auto_send: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    users: Mapped[list["User"]] = relationship(back_populates="tenant")
    agents: Mapped[list["Agent"]] = relationship(back_populates="tenant")  # noqa: F821


class User(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    role: Mapped[str] = mapped_column(String(50), default="member")  # owner, admin, member

    tenant: Mapped["Tenant"] = relationship(back_populates="users")
