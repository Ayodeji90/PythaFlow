"""Telegram MTProto channel adapter — normalizes MTProto updates to InboundMessage.

The adapter handles both Bot API webhook updates and MTProto Update objects,
converting them to the canonical InboundMessage the shared pipeline expects.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...models.enums import ChannelType
from ...schemas.message import InboundMessage, SenderRef


@dataclass
class TelegramInbound:
    """Normalised inbound Telegram message, independent of the update source."""

    chat_id: int
    user_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    text: str
    message_id: int
    date: int
    raw: dict[str, Any]

    @property
    def is_private(self) -> bool:
        """Check if this is a private (1:1) chat."""
        return True  # Will be validated in from_update

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
        """Build from a Bot API webhook update (for webhook-based receiving)."""
        msg = update.get("message") or update.get("edited_message")
        if not msg or "text" not in msg:
            return None

        chat = msg.get("chat", {})
        user = msg.get("from", {})

        # Only process private chats for MVP
        if chat.get("type") != "private":
            return None

        return TelegramInbound(
            chat_id=chat["id"],
            user_id=user.get("id", 0),
            username=user.get("username"),
            first_name=user.get("first_name"),
            last_name=user.get("last_name"),
            text=msg["text"],
            message_id=msg["message_id"],
            date=msg.get("date", 0),
            raw=update,
        )

    @staticmethod
    def from_mtproto_update(update: Any) -> TelegramInbound | None:
        """Build from an MTProto Update object (for long polling/MTPoto).

        This expects a telethon UpdateNewMessage or similar.
        """
        try:
            from telethon.tl.types import Message, PeerUser, UpdateNewMessage

            if not isinstance(update, UpdateNewMessage):
                return None

            msg = update.message
            if not isinstance(msg, Message) or not msg.message:
                return None

            # Get chat/user info
            peer_id = msg.peer_id
            chat_id = None
            user_id = None

            if isinstance(peer_id, PeerUser):
                user_id = peer_id.user_id
                chat_id = user_id  # Private chat: chat_id == user_id
            else:
                # Channel/Chat - for MVP we only handle private
                chat_id = getattr(peer_id, "channel_id", None) or getattr(peer_id, "chat_id", None)
                if chat_id is not None:
                    chat_id = int(chat_id)
                # For non-private, we'd need to resolve the user from msg.from_id
                if msg.from_id and hasattr(msg.from_id, "user_id"):
                    user_id = msg.from_id.user_id

            if chat_id is None or user_id is None:
                return None

            return TelegramInbound(
                chat_id=chat_id,
                user_id=user_id,
                username=None,  # Would need entity resolution
                first_name=None,
                last_name=None,
                text=msg.message,
                message_id=msg.id,
                date=int(msg.date.timestamp()) if msg.date else 0,
                raw={"mtproto": True, "update_id": update.id if hasattr(update, "id") else 0},
            )
        except ImportError:
            return None
        except Exception:
            return None


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