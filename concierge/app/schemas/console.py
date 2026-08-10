"""Staff console API schemas (Day 17).

Wire DTOs for the conversation list + transcript endpoints. Deliberately flat
and console-shaped — the console is a client of the API, and these are its
view models (a `Message.meta["delivery"]` dict becomes the `delivery_ticks`
the UI renders as ✓✓).
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ConversationListItem(BaseModel):
    id: UUID
    channel_type: str
    guest_name: str | None = None
    guest_phone: str | None = None
    last_message_preview: str = ""
    status: str
    # 1 when the newest message is from the guest (needs a reply), else 0.
    unread: int = 0
    updated_at: datetime | None = None


class ConversationListResponse(BaseModel):
    conversations: list[ConversationListItem]
    total: int


class ConsoleMessage(BaseModel):
    id: UUID
    role: str
    content: str
    content_type: str = "text"
    created_at: datetime
    # Day 16: whatsapp delivery/read receipts, e.g. {"delivered": "...", "read": "..."}
    delivery_ticks: dict = Field(default_factory=dict)


class LinkedRequest(BaseModel):
    id: UUID
    type: str
    status: str
    priority: str = "normal"
    summary: str | None = None
    confidence: float | None = None
    created_at: datetime


class GuestContext(BaseModel):
    id: UUID | None = None
    display_name: str | None = None
    phone: str | None = None
    preferences: dict = Field(default_factory=dict)


class ConversationDetail(BaseModel):
    id: UUID
    channel_type: str
    status: str
    external_thread_id: str | None = None
    guest: GuestContext | None = None
    messages: list[ConsoleMessage]
    requests: list[LinkedRequest]
    updated_at: datetime | None = None
