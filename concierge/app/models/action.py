"""Action — an audit record of every tool the agent invoked (with inputs and
outputs). Approval — the human-in-the-loop gate that must flip to `approved`
before a guarded write is committed."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin, TimestampMixin, UUIDMixin
from .enums import ActionStatus, ApprovalStatus, pg_enum


class Action(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "actions"

    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    type: Mapped[str] = mapped_column(String(80))  # tool name, e.g. "create_reservation"
    input: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    output: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    status: Mapped[ActionStatus] = mapped_column(
        pg_enum(ActionStatus, "action_status"),
        default=ActionStatus.proposed,
        server_default=ActionStatus.proposed.value,
    )


class Approval(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "approvals"

    action_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actions.id", ondelete="CASCADE"), nullable=True
    )
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reservations.id", ondelete="CASCADE"), nullable=True
    )
    status: Mapped[ApprovalStatus] = mapped_column(
        pg_enum(ApprovalStatus, "approval_status"),
        default=ApprovalStatus.pending,
        server_default=ApprovalStatus.pending.value,
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
