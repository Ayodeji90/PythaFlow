"""Telegram adapter unit tests — webhook parsing guards and the canonical
InboundMessage mapping (mirrors test_whatsapp_adapter.py)."""

from __future__ import annotations

from app.channels.telegram.adapter import TelegramAdapter, TelegramInbound
from app.models.enums import ChannelType


def _update(text: str, *, chat_type: str = "private") -> dict:
    return {
        "update_id": 1,
        "message": {
            "message_id": 7,
            "date": 1700000000,
            "chat": {"id": 123456789, "type": chat_type},
            "from": {
                "id": 987654321,
                "username": "ada_guest",
                "first_name": "Ada",
                "last_name": "Guest",
            },
            "text": text,
        },
    }


class TestFromWebhookUpdate:
    def test_happy_path_parses_fields(self):
        inbound = TelegramInbound.from_webhook_update(_update("hello"))
        assert inbound is not None
        assert inbound.chat_id == 123456789
        assert inbound.user_id == 987654321
        assert inbound.text == "hello"
        assert inbound.message_id == 7
        assert inbound.display_name == "Ada Guest"

    def test_private_chat_only(self):
        assert TelegramInbound.from_webhook_update(_update("x", chat_type="group")) is None
        assert TelegramInbound.from_webhook_update(_update("x", chat_type="supergroup")) is None
        assert TelegramInbound.from_webhook_update(_update("x", chat_type="channel")) is None
        assert TelegramInbound.from_webhook_update(_update("x", chat_type="private")) is not None

    def test_no_text_returns_none(self):
        update = _update("photo")
        del update["message"]["text"]
        update["message"]["photo"] = [{"file_id": "f", "width": 1, "height": 1}]
        assert TelegramInbound.from_webhook_update(update) is None

    def test_edited_message_supported(self):
        update = _update("original")
        update["edited_message"] = update.pop("message")
        inbound = TelegramInbound.from_webhook_update(update)
        assert inbound is not None
        assert inbound.text == "original"

    def test_is_private_is_honest(self):
        private = TelegramInbound.from_webhook_update(_update("hi"))
        assert private is not None
        assert private.is_private is True
        assert private.chat_type == "private"


class TestToInbound:
    def test_maps_canonical_contract(self):
        inbound = TelegramInbound.from_webhook_update(_update("Any tables for two?"))
        assert inbound is not None
        msg = TelegramAdapter.to_inbound(inbound, tenant_slug="demo")
        assert msg.tenant_slug == "demo"
        assert msg.channel == ChannelType.telegram
        assert msg.conversation_ref == "123456789"  # chat_id = stable thread key
        assert msg.sender.id == "987654321"
        assert msg.sender.name == "Ada Guest"
        assert msg.content == "Any tables for two?"
        assert msg.metadata["source"] == "telegram"
        assert msg.metadata["telegram"]["chat_id"] == 123456789
