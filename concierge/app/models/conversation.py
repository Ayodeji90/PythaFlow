"""Conversation (a thread with a guest on a channel) and Message (one turn)."""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin, TimestampMixin, UUIDMixin
from .enums import ChannelType, ConversationStatus, MessageRole, pg_enum


class Conversation(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        # Fast lookup when a provider webhook arrives with a thread id.
        Index("ix_conversations_tenant_thread", "tenant_id", "external_thread_id"),
    )

    guest_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guests.id", ondelete="SET NULL"), nullable=True
    )
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="SET NULL"), nullable=True
    )
    channel_type: Mapped[ChannelType] = mapped_column(pg_enum(ChannelType, "channel_type"))
    external_thread_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    language: Mapped[str | None] = mapped_column(String(12), nullable=True)
    status: Mapped[ConversationStatus] = mapped_column(
        pg_enum(ConversationStatus, "conversation_status"),
        default=ConversationStatus.active,
        server_default=ConversationStatus.active.value,
    )
    # Orchestrator scratchpad (current intent, slots being filled, etc.).
    state: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )


class Message(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[MessageRole] = mapped_column(pg_enum(MessageRole, "message_role"))
    content: Mapped[str] = mapped_column(Text, default="", server_default="")
    content_type: Mapped[str] = mapped_column(String(20), default="text", server_default="text")
    # tokens, latency, tool-call refs, provider ids …
    meta: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
