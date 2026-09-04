"""Pydantic schemas for the staff-console conversation endpoints (Day 17)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class ConversationListItem(BaseModel):
    id: UUID
    channel_type: str
    external_thread_id: str | None = None
    guest_name: str | None = None
    guest_phone: str | None = None
    last_message_preview: str
    last_message_at: datetime
    status: str
    has_pending_request: bool = False


class ConversationListResponse(BaseModel):
    total: int
    conversations: list[ConversationListItem]


class TranscriptMessage(BaseModel):
    id: UUID
    role: str
    content: str
    content_type: str | None = None
    created_at: datetime
    meta: dict[str, Any] | None = None


class ConversationDetailResponse(BaseModel):
    id: UUID
    channel_type: str
    external_thread_id: str | None = None
    guest_name: str | None = None
    guest_phone: str | None = None
    status: str
    created_at: datetime
    messages: list[TranscriptMessage]
    linked_request_id: UUID | None = None
