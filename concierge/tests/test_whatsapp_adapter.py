"""Day-15 proof: a WhatsApp message round-trips through the SAME brain.

- the standard Meta/360dialog payload maps to the canonical InboundMessage
- bad/missing X-Hub-Signature-256 → 401, body never processed
- a WhatsApp conversation produces a concierge reply via the same engine path
- unknown business numbers are dropped, never crashed
- the brain (orchestrator + tools) contains no WhatsApp coupling
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import app.routers.whatsapp as whatsapp_router
from app.channels.whatsapp.adapter import (
    WhatsAppAdapter,
    example_payload,
    parse_whatsapp_payload,
)
from app.channels.whatsapp.client import MockWhatsAppClient
from app.config import Settings
from app.db import SessionLocal
from app.main import app
from app.models import Channel, Conversation, Guest, Tenant
from app.models.enums import ChannelType
from app.orchestrator.echo import EchoOrchestrator
from app.routers.whatsapp import _is_valid_signature

SECRET = "test-secret"


def _sign(raw: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def _wa_headers(payload: dict, secret: str = SECRET) -> dict:
    raw = json.dumps(payload).encode()
    return {"content-type": "application/json", "X-Hub-Signature-256": _sign(raw, secret)}


# ── adapter / parser (pure, no network, no DB) ──────────────────────────


async def test_payload_maps_to_inbound_message():
    messages, statuses = parse_whatsapp_payload(example_payload())
    assert statuses == []
    assert len(messages) == 1
    wa = messages[0]
    assert wa.wa_id == "15551234567"
    assert wa.text == "table for 4 on friday at 8"
    assert wa.phone_number_id == "1000"

    msg = WhatsAppAdapter.to_inbound(wa, tenant_slug="demo")
    assert msg.channel == ChannelType.whatsapp
    assert msg.conversation_ref == "15551234567"  # thread = the guest's number
    assert msg.sender.phone == "15551234567"
    assert msg.sender.name == "Chidera"
    assert msg.content == "table for 4 on friday at 8"
    assert msg.metadata["source"] == "whatsapp"
    assert msg.metadata["wa_message_id"] == "wamid.ABC123"


async def test_status_callbacks_returned_separately():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "1",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "statuses": [
                                {"id": "wamid.1", "status": "delivered", "timestamp": "1750000000"}
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    messages, statuses = parse_whatsapp_payload(payload)
    assert messages == []
    assert len(statuses) == 1
    assert statuses[0]["status"] == "delivered"


async def test_signature_verification():
    raw = b'{"hello": "world"}'
    good = _sign(raw)
    assert _is_valid_signature(SECRET, raw, good)
    assert not _is_valid_signature(SECRET, raw, "sha256=" + "0" * 64)
    assert not _is_valid_signature(SECRET, raw, "")
    assert not _is_valid_signature("", raw, good)  # no secret → never valid


# ── endpoint tests ───────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def whatsapp_tenant():
    """Committed tenant + whatsapp channel for endpoint tests (app uses its own
    session). The business number is the Channel.external_id used for routing."""
    slug = f"wa-{uuid.uuid4().hex[:8]}"
    async with SessionLocal() as s:
        t = Tenant(slug=slug, name="WA Test")
        s.add(t)
        await s.flush()
        s.add(
            Channel(
                tenant_id=t.id,
                type=ChannelType.whatsapp,
                external_id="1000",  # phone_number_id from example_payload()
                active=True,
            )
        )
        await s.commit()
        tid = t.id
    yield slug
    async with SessionLocal() as s:
        t = await s.get(Tenant, tid)
        if t:
            await s.delete(t)
            await s.commit()


def _patch_settings(monkeypatch, **overrides):
    """Point the router's get_settings at a Settings with the given overrides."""
    base = {"WHATSAPP_APP_SECRET": SECRET, **overrides}
    monkeypatch.setattr(whatsapp_router, "get_settings", lambda: Settings(**base))


async def test_webhook_rejects_bad_signature(monkeypatch):
    _patch_settings(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = example_payload()
        # valid signature → 200 (no tenant configured yet, message dropped)
        r_ok = await client.post(
            "/webhooks/whatsapp",
            content=json.dumps(payload),
            headers=_wa_headers(payload),
        )
        assert r_ok.status_code == 200

        # tampered body → 401
        tampered = {"content-type": "application/json", "X-Hub-Signature-256": _sign(b"tampered")}
        r_bad = await client.post(
            "/webhooks/whatsapp",
            content=json.dumps(payload),
            headers=tampered,
        )
        assert r_bad.status_code == 401

        # missing signature → 401
        r_none = await client.post(
            "/webhooks/whatsapp",
            content=json.dumps(payload),
            headers={"content-type": "application/json"},
        )
        assert r_none.status_code == 401


async def test_webhook_verification_challenge(monkeypatch):
    _patch_settings(monkeypatch, WHATSAPP_VERIFY_TOKEN="v-token")
    transport = ASGITransport(app=app)
    params_ok = {"hub.mode": "subscribe", "hub.verify_token": "v-token", "hub.challenge": "C1"}
    params_bad = {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "C2"}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/webhooks/whatsapp", params=params_ok)
        assert r.status_code == 200
        assert r.text == "CHALLENGE_123"

        r_bad = await client.get("/webhooks/whatsapp", params=params_bad)
        assert r_bad.status_code == 403


async def test_whatsapp_message_roundtrips_through_engine(monkeypatch, whatsapp_tenant):
    """A WhatsApp message → shared pipeline → echo reply sent back via the BSP
    client, conversation persisted with channel_type=whatsapp, guest with phone."""
    _patch_settings(monkeypatch, WHATSAPP_BSP="mock", WHATSAPP_TOKEN="")
    mock = MockWhatsAppClient()
    monkeypatch.setattr(whatsapp_router, "build_whatsapp_client", lambda settings: mock)

    prev = app.state.orchestrator
    app.state.orchestrator = EchoOrchestrator()
    try:
        payload = example_payload()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/webhooks/whatsapp",
                content=json.dumps(payload),
                headers=_wa_headers(payload),
            )
            assert r.status_code == 200
            assert r.json()["detail"].startswith("processed")
    finally:
        app.state.orchestrator = prev

    # the reply went out over WhatsApp
    assert len(mock.sent) == 1
    sent = mock.sent[0]
    assert sent["kind"] == "text"
    assert sent["to"] == "15551234567"
    assert sent["body"] == "You said: table for 4 on friday at 8"

    # the conversation is a whatsapp thread with a phone-identified guest
    async with SessionLocal() as s:
        conv = (
            await s.execute(
                select(Conversation).where(
                    Conversation.external_thread_id == "15551234567",
                )
            )
        ).scalar_one()
        assert conv.channel_type == ChannelType.whatsapp
        assert conv.guest_id is not None
        guest = await s.get(Guest, conv.guest_id)
        assert guest.phone == "15551234567"


async def test_unknown_business_number_dropped(monkeypatch):
    """No active whatsapp channel for the number → 200 accepted, nothing sent."""
    _patch_settings(monkeypatch)
    mock = MockWhatsAppClient()
    monkeypatch.setattr(whatsapp_router, "build_whatsapp_client", lambda settings: mock)

    payload = example_payload()
    # point the payload at a business number nobody has configured
    metadata = payload["entry"][0]["changes"][0]["value"]["metadata"]
    metadata["phone_number_id"] = "9999"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/webhooks/whatsapp",
            content=json.dumps(payload),
            headers=_wa_headers(payload),
        )
        assert r.status_code == 200
    assert mock.sent == []


def test_zero_brain_change_guard():
    """Day-15 diff proof, structural: the brain (orchestrator + tools) must not
    import the WhatsApp channel — the adapter is the only new mapping code."""
    root = Path(__file__).resolve().parents[1]
    for sub in ("app/orchestrator", "app/tools"):
        for path in (root / sub).rglob("*.py"):
            for line in path.read_text().splitlines():
                if "channels.whatsapp" in line or line.strip().startswith("import whatsapp"):
                    raise AssertionError(f"brain coupled to WhatsApp in {path}: {line}")
