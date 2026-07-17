"""Guest — the end customer the concierge talks to. One guest may reach out on
several channels, so we keep per-channel `handles` plus a phone for matching."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin, TimestampMixin, UUIDMixin


class Guest(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "guests"

    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    handles: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    preferences: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    consent: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
