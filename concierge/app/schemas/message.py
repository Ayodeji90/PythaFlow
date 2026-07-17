"""The canonical message contract — the heart of the channel-agnostic design.

Every channel (web chat today; WhatsApp, SMS, voice later) normalises whatever
its provider sends into an `InboundMessage`, and renders the `OutboundChunk`s the
orchestrator streams back. **The brain never sees channel specifics.**

These are wire/in-flight DTOs and are deliberately separate from the persisted
`app.models.Message` row — the transport contract shouldn't be coupled to storage.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from ..models.enums import ChannelType


class SenderRef(BaseModel):
    """Who sent it, in channel-neutral terms. Web chat only has a session id;
    WhatsApp will carry a phone; Instagram a handle."""

    id: str
    name: str | None = None
    phone: str | None = None
    handle: str | None = None


class InboundMessage(BaseModel):
    tenant_slug: str
    channel: ChannelType
    # The channel's own thread identifier (web-chat session id, WhatsApp thread…).
    # Resolved to a Conversation via the (tenant_id, external_thread_id) index.
    conversation_ref: str
    sender: SenderRef
    content: str
    content_type: Literal["text", "audio"] = "text"
    locale: str | None = None
    received_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    # Escape hatch for channel-specific extras (provider message ids, etc.)
    metadata: dict = Field(default_factory=dict)


class OutboundChunk(BaseModel):
    """One frame streamed back from the orchestrator.

    - `typing`  — a hint the channel may render as a typing indicator
    - `token`   — a streamed fragment (Day 4); concatenate them
    - `message` — a complete message
    - `action`  — a tool/side-effect notification (Day 8+)
    - `done`    — the turn is finished
    - `error`   — something failed; `content` explains
    """

    type: Literal["token", "message", "typing", "action", "done", "error"]
    content: str | None = None
    metadata: dict = Field(default_factory=dict)
