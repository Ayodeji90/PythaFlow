"""Request — the central work item connecting conversation to fulfilment.

Every tool that writes (draft_reservation, modify, cancel, order) creates a
Request. Staff triage from a single queue, approve/reject, and the orchestrator
worker picks up approved requests for fulfilment.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin, TimestampMixin, UUIDMixin
from .enums import ChannelType, RequestPriority, RequestStatus, RequestType, pg_enum


class Request(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "requests"
    __table_args__ = (
        Index("ix_requests_tenant_status", "tenant_id", "status"),
        Index("ix_requests_conversation", "conversation_id"),
    )

    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    guest_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guests.id", ondelete="SET NULL"), nullable=True
    )
    channel_type: Mapped[ChannelType | None] = mapped_column(
        pg_enum(ChannelType, "channel_type"), nullable=True
    )
    type: Mapped[RequestType] = mapped_column(
        pg_enum(RequestType, "request_type"),
        default=RequestType.enquiry,
        server_default=RequestType.enquiry.value,
    )
    status: Mapped[RequestStatus] = mapped_column(
        pg_enum(RequestStatus, "request_status"),
        default=RequestStatus.new,
        server_default=RequestStatus.new.value,
    )
    priority: Mapped[RequestPriority] = mapped_column(
        pg_enum(RequestPriority, "request_priority"),
        default=RequestPriority.normal,
        server_default=RequestPriority.normal.value,
    )
    summary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default="'{}'::jsonb", nullable=False
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolution: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
