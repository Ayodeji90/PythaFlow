"""Tenant (the hospitality business — root of isolation) and User (staff)."""
from __future__ import annotations

from sqlalchemy import String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin, TimestampMixin, UUIDMixin
from .enums import UserRole, pg_enum


class Tenant(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "tenants"

    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    brand_voice: Mapped[str] = mapped_column(Text, default="", server_default="")
    languages: Mapped[list] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb"), nullable=False
    )
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", server_default="UTC")
    hours: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    config: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )


class User(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )

    email: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[UserRole] = mapped_column(
        pg_enum(UserRole, "user_role"), default=UserRole.staff, server_default=UserRole.staff.value
    )
    auth_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
