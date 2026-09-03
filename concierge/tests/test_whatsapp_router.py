"""WhatsApp router endpoint tests — ASGI-level tests for the inbound webhook,
health check, and status callback.

Uses httpx.AsyncClient with ASGITransport so everything runs in the same event
loop as the async DB session — avoids the "different loop" error from mixing
TestClient's thread pool with asyncpg connections.

Covers end-to-end code paths in ``app/routers/whatsapp.py`` that the unit-level
helper tests (in test_whatsapp_hardening.py) can't reach — signature validation,
empty body handling, dedup, tenant resolution, and the status callback.
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.deps import get_db
from app.main import create_app
from app.models import Channel, Conversation, Message, Tenant
from app.models.enums import ChannelType, MessageRole
from app.orchestrator.echo import EchoOrchestrator

# ── Fixtures ─────────────────────────────────────────────────────────────────


def _make_app(session=None, *, enable_signatures: bool = False):
    """Build the FastAPI app with overrides for testing.

    If ``session`` is provided, the DB dependency is overridden to yield it
    (the caller is responsible for keeping it alive in the right event loop).
    """
    app = create_app()

    if session is not None:
        async def _override_db():
            yield session

        app.dependency_overrides[get_db] = _override_db

    app.state.orchestrator = EchoOrchestrator()

    # Disable signature validation by default; the enable_signatures kwarg
    # controls it for the specific test that needs it.
    patch_settings = patch("app.routers.whatsapp.get_settings")
    mock_settings = patch_settings.start()
    s = Settings(
        WHATSAPP_VALIDATE_SIGNATURE=enable_signatures,
        WHATSAPP_DEFAULT_TENANT="",
        TWILIO_AUTH_TOKEN="secret" if enable_signatures else "",
    )
    mock_settings.return_value = s
    return app, patch_settings


@pytest_asyncio.fixture
async def async_client(session):
    """``httpx.AsyncClient`` wired to the app with a real DB session and
    EchoOrchestrator, running in the test's event loop."""
    app, patch_ctx = _make_app(session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        patch_ctx.stop()


@pytest_asyncio.fixture
async def client_sans_db():
    """``httpx.AsyncClient`` with NO DB override — the endpoint will try the
    real SessionLocal which works for tests that return before any DB call."""
    app, patch_ctx = _make_app(None)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        patch_ctx.stop()


def _wa_form(body: str, **kwargs) -> dict[str, str]:
    """Standard Twilio-style form POST body for WhatsApp."""
    d = {
        "From": "whatsapp:+2348012345678",
        "To": "whatsapp:+14155238886",
        "Body": body,
        "WaId": "2348012345678",
        "ProfileName": "Ada",
        "MessageSid": f"SM{uuid.uuid4().hex[:12]}",
    }
    d.update(kwargs)
    return d


@pytest_asyncio.fixture
async def tenant_with_channel(session) -> Tenant:
    """Create a tenant + WhatsApp Channel row for tenant-resolution tests."""
    tenant = Tenant(slug=f"wa-router-{uuid.uuid4().hex[:8]}", name="Router Test")
    session.add(tenant)
    await session.flush()
    channel = Channel(
        tenant_id=tenant.id,
        type=ChannelType.whatsapp,
        external_id="whatsapp:+14155238886",
        active=True,
    )
    session.add(channel)
    await session.flush()
    return tenant


# ── Health endpoint ──────────────────────────────────────────────────────────


class TestWhatsappHealth:
    async def test_health_returns_ok(self, client_sans_db):
        resp = await client_sans_db.get("/webhooks/whatsapp")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "channel": "whatsapp"}


# ── Inbound webhook ──────────────────────────────────────────────────────────


class TestInboundWhatsapp:
    async def test_signature_validation_fails_403(self, client_sans_db):
        """When signature validation is enabled and the signature is bad, return 403."""
        # Rebuild with signatures on — we need to create a fresh app for this.
        app, patch_ctx = _make_app(None, enable_signatures=True)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/webhooks/whatsapp",
                    data=_wa_form("hi"),
                    headers={"X-Twilio-Signature": "bad"},
                )
            assert resp.status_code == 403
            assert "invalid" in resp.text.lower()
        finally:
            patch_ctx.stop()

    async def test_empty_body_returns_empty_twiml(self, client_sans_db):
        resp = await client_sans_db.post("/webhooks/whatsapp", data=_wa_form(""))
        assert resp.status_code == 200
        assert "<?xml" in resp.text
        assert "<Response></Response>" in resp.text

    async def test_tenant_not_found_returns_empty_twiml(self, async_client):
        """When the "To" number matches no Channel, return empty Twiml."""
        resp = await async_client.post(
            "/webhooks/whatsapp",
            data=_wa_form("hi", To="whatsapp:+19999999999"),
        )
        assert resp.status_code == 200
        assert "<Response></Response>" in resp.text

    async def test_happy_path_processes(
        self, async_client, session, tenant_with_channel
    ):
        """Valid message → EchoOrchestrator processes → 200 Twiml."""
        resp = await async_client.post(
            "/webhooks/whatsapp",
            data=_wa_form("Any tables for two?"),
        )
        assert resp.status_code == 200
        assert "<Response></Response>" in resp.text

    async def test_outbound_failure_does_not_500(
        self, async_client, session, tenant_with_channel
    ):
        """Outbound send failure is caught — webhook still returns 200."""
        resp = await async_client.post(
            "/webhooks/whatsapp",
            data=_wa_form("Hello from Ada"),
        )
        assert resp.status_code == 200
        assert "<Response></Response>" in resp.text


# ── Status callback ──────────────────────────────────────────────────────────


class TestWhatsappStatus:
    async def test_status_updates_known_message(
        self, async_client, session, tenant_with_channel
    ):
        """A delivery receipt with a known SID updates the message status."""
        tenant = tenant_with_channel
        conv = Conversation(
            tenant_id=tenant.id,
            channel_type=ChannelType.whatsapp,
            external_thread_id="234000111222",
        )
        session.add(conv)
        await session.flush()
        msg = Message(
            tenant_id=tenant.id,
            conversation_id=conv.id,
            role=MessageRole.assistant,
            content="test message",
            meta={"whatsapp_sid": "SMknown", "whatsapp_status": "sent"},
        )
        session.add(msg)
        await session.commit()

        resp = await async_client.post(
            "/webhooks/whatsapp/status",
            data={"MessageSid": "SMknown", "MessageStatus": "read"},
        )
        assert resp.status_code == 200

        await session.refresh(msg)
        assert msg.meta["whatsapp_status"] == "read"

    async def test_status_unknown_sid_noop(self, async_client, session):
        """Status callback with unknown SID returns 200 without error."""
        resp = await async_client.post(
            "/webhooks/whatsapp/status",
            data={"MessageSid": "SMnonexistent", "MessageStatus": "delivered"},
        )
        assert resp.status_code == 200

    async def test_status_empty_fields_noop(self, async_client):
        """Status with no sid/status fields returns 200."""
        resp = await async_client.post(
            "/webhooks/whatsapp/status",
            data={"some": "irrelevant"},
        )
        assert resp.status_code == 200

    async def test_status_with_invalid_signature_403(self, client_sans_db):
        """Status callbacks are also signature-validated."""
        app, patch_ctx = _make_app(None, enable_signatures=True)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/webhooks/whatsapp/status",
                    data={"MessageSid": "SMx", "MessageStatus": "delivered"},
                    headers={"X-Twilio-Signature": "bad"},
                )
            assert resp.status_code == 403
        finally:
            patch_ctx.stop()