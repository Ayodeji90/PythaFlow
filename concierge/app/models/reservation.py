"""Reservation — a booking the concierge creates or changes. The unique
`(tenant_id, idempotency_key)` makes a duplicate booking *impossible* even if the
LLM retries the tool call."""
from __future__ import annotations

import uuid
from datetime import date as date_type
from datetime import time as time_type

from sqlalchemy import Date, ForeignKey, Integer, String, Text, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin, TimestampMixin, UUIDMixin
from .enums import ChannelType, ReservationStatus, pg_enum


class Reservation(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "reservations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_reservations_tenant_idem"),
    )

    guest_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guests.id", ondelete="SET NULL"), nullable=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    party_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    time: Mapped[time_type | None] = mapped_column(Time, nullable=True)
    area: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ReservationStatus] = mapped_column(
        pg_enum(ReservationStatus, "reservation_status"),
        default=ReservationStatus.pending,
        server_default=ReservationStatus.pending.value,
    )
    source_channel: Mapped[ChannelType | None] = mapped_column(
        pg_enum(ChannelType, "channel_type"), nullable=True
    )
    external_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
