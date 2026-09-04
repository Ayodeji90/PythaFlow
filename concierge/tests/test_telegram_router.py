"""Telegram router endpoint tests — ASGI-level tests for the inbound webhook.

Uses httpx.AsyncClient with ASGITransport (same pattern as test_whatsapp_router)
so everything runs in the same event loop as the async DB session.

Covers the code paths that the old MTProto implementation got wrong: per-tenant
routing (each venue's bot token), secret-token validation, update dedup, the
private-chat-only guard, unknown-tenant discard, and — critically — that the
reply is delivered through the venue's own bot client (one identity end to end).
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.deps import get_db
from app.main import create_app
from app.models import Channel, Tenant
from app.models.enums import ChannelType
from app.orchestrator.echo import EchoOrchestrator


class FakeTelegramClient:
    """Records send_text calls so tests can assert the reply went out."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_text(self, *, chat_id: int, text: str) -> str:
        self.sent.append((chat_id, text))
        return "42"


def _make_app(session=None, *, secret: str = "", default_tenant: str = ""):
    """Build the FastAPI app with overrides + test doubles for Telegram.

    Patches the router's get_settings (so the webhook secret / default tenant
    are controllable) and build_telegram_client (so no real network call is
    made). Records every bot token handed to the client builder.
    """
    app = create_app()

    if session is not None:
        async def _override_db():
            yield session

        app.dependency_overrides[get_db] = _override_db

    app.state.orchestrator = EchoOrchestrator()

    patch_settings = patch("app.channels.telegram.router.get_settings")
    mock_settings = patch_settings.start()
    mock_settings.return_value = Settings(
        TELEGRAM_WEBHOOK_SECRET=secret,
        TELEGRAM_DEFAULT_TENANT=default_tenant,
    )

    fake = FakeTelegramClient()
    tokens: list[str | None] = []

    def _fake_build(bot_token: str | None):
        tokens.append(bot_token)
        return fake

    patch_build = patch(
        "app.channels.telegram.router.build_telegram_client",
        side_effect=_fake_build,
    )
    patch_build.start()
    return app, patch_settings, patch_build, fake, tokens


@pytest_asyncio.fixture
async def async_client(session):
    """``httpx.AsyncClient`` wired to the app with a real DB session and
    EchoOrchestrator, running in the test's event loop."""
    app, patch_settings, patch_build, fake, tokens = _make_app(session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, fake, tokens
    finally:
        patch_build.stop()
        patch_settings.stop()


VENUE_SECRET = "venue-secret"


async def _post(client: AsyncClient, path: str, update: dict, *, secret: str = VENUE_SECRET):
    """POST a Telegram update with the venue's registered webhook secret."""
    headers = {"X-Telegram-Bot-Api-Secret-Token": secret} if secret is not None else {}
    return await client.post(path, json=update, headers=headers)


def _tg_update(
    text: str,
    *,
    chat_type: str = "private",
    update_id: int | None = None,
) -> dict:
    """Standard Bot API webhook update for a text message in a private chat."""
    return {
        "update_id": update_id if update_id is not None else (uuid.uuid4().int & 0xFFFFFFFFFFFF),
        "message": {
            "message_id": 1,
            "date": 1700000000,
            "chat": {"id": 123456789, "type": chat_type},
            "from": {
                "id": 987654321,
                "username": "ada_guest",
                "first_name": "Ada",
            },
            "text": text,
        },
    }


@pytest_asyncio.fixture
async def tenant_with_channel(session) -> Tenant:
    """Tenant + active Telegram Channel row with its own bot token + secret."""
    tenant = Tenant(slug=f"tg-router-{uuid.uuid4().hex[:8]}", name="Router Test")
    session.add(tenant)
    await session.flush()
    session.add(
        Channel(
            tenant_id=tenant.id,
            type=ChannelType.telegram,
            external_id="@venue_bot",
            active=True,
            config={
                "bot_token": "123456:TESTTOKEN",
                "webhook_secret": VENUE_SECRET,
            },
        )
    )
    await session.flush()
    return tenant


async def _make_second_tenant(session) -> Tenant:
    """A second venue with its OWN bot token — the isolation test's other half."""
    tenant = Tenant(slug=f"tg-other-{uuid.uuid4().hex[:8]}", name="Other Venue")
    session.add(tenant)
    await session.flush()
    session.add(
        Channel(
            tenant_id=tenant.id,
            type=ChannelType.telegram,
            active=True,
            config={"bot_token": "999999:OTHERTOKEN"},
        )
    )
    await session.flush()
    return tenant


# ── Health ───────────────────────────────────────────────────────────────────


class TestTelegramHealth:
    async def test_health_returns_ok(self, async_client):
        client, _, _ = async_client
        resp = await client.get("/webhooks/telegram")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "channel": "telegram"}


# ── Inbound webhook ──────────────────────────────────────────────────────────


class TestInboundTelegram:
    async def test_happy_path_replies_with_venue_bot(
        self, async_client, session, tenant_with_channel
    ):
        """Valid message → EchoOrchestrator processes → reply sent via the
        venue's own bot client (never a different identity)."""
        client, fake, tokens = async_client
        resp = await _post(
            client, f"/webhooks/telegram/{tenant_with_channel.slug}",
            _tg_update("Any tables for two?"),
        )
        assert resp.status_code == 200
        assert resp.text == "ok"
        assert fake.sent == [(123456789, "You said: Any tables for two?")]
        assert tokens[-1] == "123456:TESTTOKEN"  # the venue's own token

    async def test_secret_mismatch_403(
        self, async_client, session, tenant_with_channel
    ):
        """Wrong/missing X-Telegram-Bot-Api-Secret-Token → 403, not processed."""
        client, fake, _ = async_client
        for headers in ({"X-Telegram-Bot-Api-Secret-Token": "wrong"}, {}):
            resp = await client.post(
                f"/webhooks/telegram/{tenant_with_channel.slug}",
                json=_tg_update("hi"),
                headers=headers,
            )
            assert resp.status_code == 403
        assert fake.sent == []

    async def test_duplicate_update_skipped(self, async_client, session, tenant_with_channel):
        """Same update_id delivered twice → processed exactly once."""
        client, fake, _ = async_client
        update = _tg_update("Book a table", update_id=424242)
        for _ in range(2):
            resp = await _post(
                client, f"/webhooks/telegram/{tenant_with_channel.slug}", update
            )
            assert resp.status_code == 200
        assert len(fake.sent) == 1

    async def test_group_chat_ignored(self, async_client, session, tenant_with_channel):
        """Non-private chats (groups/channels) are out of scope — acknowledged but
        never processed."""
        client, fake, _ = async_client
        resp = await _post(
            client, f"/webhooks/telegram/{tenant_with_channel.slug}",
            _tg_update("hi everyone", chat_type="group"),
        )
        assert resp.status_code == 200
        assert fake.sent == []

    async def test_no_text_update_ignored(self, async_client, session, tenant_with_channel):
        """Media-only updates (no text) are acknowledged but not processed."""
        client, fake, _ = async_client
        update = _tg_update("photo")
        del update["message"]["text"]
        update["message"]["photo"] = [{"file_id": "x", "width": 10, "height": 10}]
        resp = await _post(
            client, f"/webhooks/telegram/{tenant_with_channel.slug}", update
        )
        assert resp.status_code == 200
        assert fake.sent == []

    async def test_unknown_tenant_discarded(self, async_client, session):
        """Shared path with no default tenant configured → discard, no error."""
        client, fake, _ = async_client
        resp = await client.post("/webhooks/telegram", json=_tg_update("hi"))
        assert resp.status_code == 200
        assert fake.sent == []

    async def test_default_tenant_shared_path(
        self, async_client, session, tenant_with_channel
    ):
        """Shared /webhooks/telegram path routes to TELEGRAM_DEFAULT_TENANT."""
        app, patch_settings, patch_build, fake, tokens = _make_app(
            session, default_tenant=tenant_with_channel.slug
        )
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await _post(client, "/webhooks/telegram", _tg_update("hi"))
            assert resp.status_code == 200
            assert fake.sent == [(123456789, "You said: hi")]
        finally:
            patch_build.stop()
            patch_settings.stop()

    async def test_per_tenant_isolation(self, async_client, session, tenant_with_channel):
        """Two venues on one deployment: each message routes to ITS OWN bot."""
        client, fake, tokens = async_client
        other = await _make_second_tenant(session)

        # Fresh update_ids — Redis dedup keys live for an hour, so fixed ids
        # would collide with earlier test runs and be skipped as duplicates.
        resp = await _post(
            client, f"/webhooks/telegram/{tenant_with_channel.slug}",
            _tg_update("table for 2"),
        )
        assert resp.status_code == 200
        assert tokens[-1] == "123456:TESTTOKEN"

        resp = await _post(
            client, f"/webhooks/telegram/{other.slug}",
            _tg_update("table for 4"),
        )
        assert resp.status_code == 200
        assert tokens[-1] == "999999:OTHERTOKEN"

        assert len(fake.sent) == 2

    async def test_dev_mode_no_secret_accepts(self, async_client, session):
        """No secret configured anywhere → dev-mode accept (logged loudly)."""
        tenant = Tenant(slug=f"tg-nosecret-{uuid.uuid4().hex[:8]}", name="No Secret")
        session.add(tenant)
        await session.flush()
        session.add(
            Channel(
                tenant_id=tenant.id,
                type=ChannelType.telegram,
                active=True,
                config={"bot_token": "555:DEVTOKEN"},
            )
        )
        await session.flush()

        client, fake, _ = async_client
        resp = await _post(
            client, f"/webhooks/telegram/{tenant.slug}", _tg_update("hi"), secret=None
        )
        assert resp.status_code == 200
        assert fake.sent == [(123456789, "You said: hi")]