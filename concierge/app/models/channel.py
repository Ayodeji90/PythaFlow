"""Channel — a configured inbound/outbound line for a tenant. The gateway routes
an incoming message to a tenant by matching the channel's `external_id`."""
from __future__ import annotations

from sqlalchemy import Boolean, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin, TimestampMixin, UUIDMixin
from .enums import ChannelType, pg_enum


class Channel(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "channels"

    type: Mapped[ChannelType] = mapped_column(pg_enum(ChannelType, "channel_type"))
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    config: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
