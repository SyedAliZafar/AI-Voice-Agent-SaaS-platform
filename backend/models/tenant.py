"""Tenant and User models — the multi-tenancy root."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class Tenant(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    plan: Mapped[str] = mapped_column(String(50), default="trial")

    users: Mapped[list["User"]] = relationship(back_populates="tenant")
    agents: Mapped[list["Agent"]] = relationship(back_populates="tenant")  # noqa: F821


class User(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    role: Mapped[str] = mapped_column(String(50), default="member")  # owner, admin, member

    tenant: Mapped["Tenant"] = relationship(back_populates="users")
