"""Telegram Bot API client unit tests.

The core assertion is the identity fix: outbound is a plain HTTPS POST to
api.telegram.org/bot<TOKEN>/sendMessage — a bot's own token, never a user
session. Uses httpx.MockTransport so no real network call is made.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.channels.telegram.client import (
    TELEGRAM_API_BASE,
    BotApiTelegramClient,
    NullTelegramClient,
)


def _client(handler, *, token: str = "123456:TESTTOKEN"):
    transport = httpx.MockTransport(handler)
    return BotApiTelegramClient(bot_token=token, transport=transport)


class TestBotApiClient:
    async def test_send_text_posts_to_bot_endpoint(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["json"] = json.loads(request.content)
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})

        client = _client(handler)
        message_id = await client.send_text(chat_id=123, text="hello")

        assert message_id == "7"
        assert captured["url"] == f"{TELEGRAM_API_BASE}/bot123456:TESTTOKEN/sendMessage"
        assert captured["json"] == {"chat_id": 123, "text": "hello"}

    async def test_long_message_splits_at_4096(self):
        requests_seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests_seen.append(json.loads(request.content))
            return httpx.Response(
                200, json={"ok": True, "result": {"message_id": len(requests_seen)}}
            )

        client = _client(handler)
        long_text = "x" * 9000
        message_ids = await client.send_text(chat_id=123, text=long_text)

        assert len(requests_seen) == 3  # 4096 + 4096 + 808
        assert all(r["chat_id"] == 123 for r in requests_seen)
        assert len(requests_seen[0]["text"]) == 4096
        assert len(requests_seen[2]["text"]) == 9000 - 2 * 4096
        assert message_ids == "1,2,3"

    async def test_boundary_exactly_4096_single_request(self):
        requests_seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests_seen.append(request)
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

        client = _client(handler)
        await client.send_text(chat_id=1, text="x" * 4096)
        assert len(requests_seen) == 1

    async def test_api_error_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"ok": False, "description": "bad token"})

        client = _client(handler)
        with pytest.raises(httpx.HTTPStatusError):
            await client.send_text(chat_id=1, text="hi")


class TestNullClient:
    async def test_null_client_returns_sentinel(self):
        client = NullTelegramClient()
        assert await client.send_text(chat_id=1, text="hi") == "null-telegram"
