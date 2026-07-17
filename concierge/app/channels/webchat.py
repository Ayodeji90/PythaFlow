"""Web-chat adapter — the whole channel-specific surface is one small function.

Web chat is the simplest channel: the payload is already JSON we control, and the
"thread id" is just the browser session. WhatsApp (Day 15) will do the same job
against Meta's webhook payload and reuse the identical pipeline."""
from __future__ import annotations

from typing import Any

from ..models.enums import ChannelType
from ..schemas.message import InboundMessage, SenderRef


class WebChatAdapter:
    channel = ChannelType.webchat

    @classmethod
    def to_inbound(
        cls,
        *,
        tenant_slug: str,
        conversation_ref: str,
        content: str,
        payload: dict[str, Any] | None = None,
    ) -> InboundMessage:
        payload = payload or {}
        return InboundMessage(
            tenant_slug=tenant_slug,
            channel=cls.channel,
            conversation_ref=conversation_ref,
            # Anonymous: the session id is the only identity web chat has.
            sender=SenderRef(id=conversation_ref, name=payload.get("name")),
            content=content,
            locale=payload.get("locale"),
            metadata={"source": "webchat"},
        )
