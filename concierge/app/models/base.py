"""Declarative base + shared mixins.

- `Base`           the declarative root; every model registers on its metadata.
- `UUIDMixin`      a `gen_random_uuid()` UUID primary key.
- `TimestampMixin` `created_at` / `updated_at` (server-managed).
- `TenantMixin`    a `tenant_id` FK to tenants — the spine of multi-tenancy.

`Tenant` itself does NOT use `TenantMixin` (it is the root of isolation).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class Base(DeclarativeBase):
    """Declarative root for all ORM models."""


class UUIDMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TenantMixin:
    """Adds a NOT NULL, indexed `tenant_id` FK. `ondelete=CASCADE` means removing
    a tenant removes all of its data (useful for account/GDPR teardown)."""

    @declared_attr
    def tenant_id(cls) -> Mapped[uuid.UUID]:  # noqa: N805
        return mapped_column(
            UUID(as_uuid=True),
            ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
