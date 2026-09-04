"""Telegram Bot API channel adapter — normalizes Bot API webhook updates to
InboundMessage.

Receiving is webhook-only: Telegram POSTs Bot API update objects (the same JSON
shape as getUpdates) to /webhooks/telegram/{tenant_slug}. This adapter converts
them to the canonical InboundMessage the shared pipeline expects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...models.enums import ChannelType
from ...schemas.message import InboundMessage, SenderRef


@dataclass
class TelegramInbound:
    """Normalised inbound Telegram message (Bot API webhook format)."""

    chat_id: int
    user_id: int
    chat_type: str
    username: str | None
    first_name: str | None
    last_name: str | None
    text: str
    message_id: int
    date: int
    raw: dict[str, Any]

    @property
    def is_private(self) -> bool:
        """True only for 1:1 guest chats — groups/channels are out of scope (MVP)."""
        return self.chat_type == "private"

    @property
    def display_name(self) -> str | None:
        """Build a display name from available fields."""
        parts = []
        if self.first_name:
            parts.append(self.first_name)
        if self.last_name:
            parts.append(self.last_name)
        name = " ".join(parts) if parts else None
        if self.username and not name:
            name = f"@{self.username}"
        return name

    @staticmethod
    def from_webhook_update(update: dict[str, Any]) -> TelegramInbound | None:
        """Build from a Bot API webhook update.

        Returns None for non-text messages and for anything that isn't a
        private 1:1 chat (groups/channels are deliberately out of scope).
        """
        msg = update.get("message") or update.get("edited_message")
        if not msg or "text" not in msg:
            return None

        chat = msg.get("chat", {})
        user = msg.get("from", {})

        # Only process private chats for MVP (design decision D9).
        if chat.get("type") != "private":
            return None

        return TelegramInbound(
            chat_id=chat["id"],
            user_id=user.get("id", 0),
            chat_type=chat.get("type", "private"),
            username=user.get("username"),
            first_name=user.get("first_name"),
            last_name=user.get("last_name"),
            text=msg["text"],
            message_id=msg["message_id"],
            date=msg.get("date", 0),
            raw=update,
        )


class TelegramAdapter:
    """Channel adapter: Telegram → InboundMessage."""

    channel = ChannelType.telegram

    @staticmethod
    def to_inbound(inbound: TelegramInbound, *, tenant_slug: str) -> InboundMessage:
        """Convert a Telegram message to the canonical message contract."""
        return InboundMessage(
            tenant_slug=tenant_slug,
            channel=ChannelType.telegram,
            conversation_ref=str(inbound.chat_id),  # chat_id = stable thread key
            sender=SenderRef(
                id=str(inbound.user_id),
                name=inbound.display_name,
            ),
            content=inbound.text,
            locale=None,
            metadata={
                "telegram": {
                    "chat_id": inbound.chat_id,
                    "user_id": inbound.user_id,
                    "message_id": inbound.message_id,
                    "date": inbound.date,
                    "username": inbound.username,
                },
                "source": "telegram",
            },
        )
