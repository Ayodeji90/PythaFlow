"""Day-16 hardening tests: 24h service window, templates, retries, receipts.

Pure-logic tests (window/template/retry) run anywhere. The transport/webhook
tests need Postgres — they follow the same pattern as the Day-15 suite and are
exercised once `docker compose up -d db redis` + `alembic upgrade head` have
run (see HAND_OFF.md).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import app.routers.whatsapp as whatsapp_router
from app.channels.whatsapp.client import MockWhatsAppClient, WhatsAppSendError
from app.channels.whatsapp.retry import send_with_retry
from app.channels.whatsapp.templates import TEMPLATES, resolve_template_name
from app.channels.whatsapp.transport import WhatsAppTransport
from app.channels.whatsapp.window import choose_send_mode, within_service_window
from app.config import Settings
from app.db import SessionLocal
from app.main import app
from app.models import (
    Channel,
    Conversation,
    Guest,
    Message,
    Reservation,
    Tenant,
)
from app.models.enums import ChannelType, MessageRole, ReservationStatus
from app.notifications import NOTIF_MESSAGE_SENT

SECRET = "test-secret"


# ── pure: 24h service window ─────────────────────────────────────────────


async def test_choose_send_mode_in_window_text():
    last = datetime.now(UTC) - timedelta(hours=1)
    assert choose_send_mode(last, template_name="booking_confirmed") == "text"
    assert choose_send_mode(last, template_name=None) == "text"


async def test_choose_send_mode_out_of_window_template():
    last = datetime.now(UTC) - timedelta(hours=25)
    assert choose_send_mode(last, template_name="booking_confirmed") == "template"


async def test_choose_send_mode_out_of_window_no_template_raises():
    last = datetime.now(UTC) - timedelta(hours=25)
    with pytest.raises(ValueError, match="no approved template"):
        choose_send_mode(last, template_name=None)


async def test_within_service_window_boundary():
    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    just_inside = now - timedelta(hours=23, minutes=59)
    just_outside = now - timedelta(hours=24, minutes=1)
    assert within_service_window(just_inside, now) is True
    assert within_service_window(just_outside, now) is False
    assert within_service_window(None, now) is False  # no inbound yet → template
    # naive datetimes are treated as UTC (23h before → inside), never crash
    assert within_service_window(datetime(2026, 8, 9, 13, 0), now) is True


# ── pure: template registry ──────────────────────────────────────────────


async def test_resolve_template_name_precedence():
    defaults = {"confirmation": "booking_confirmed", "reminder": "booking_reminder"}
    assert resolve_template_name({"subject": "confirmation"}, defaults=defaults) == (
        "booking_confirmed"
    )
    assert resolve_template_name({"subject": "reminder"}, defaults=defaults) == (
        "booking_reminder"
    )
    assert resolve_template_name({"subject": "update"}) == "booking_updated"
    assert resolve_template_name({"template": "booking_updated"}) == "booking_updated"
    # an explicit template not in the approved registry is refused
    assert resolve_template_name({"template": "not_approved"}) is None
    assert resolve_template_name({"message": "hi"}) is None


async def test_template_registry_variable_order():
    assert TEMPLATES["booking_confirmed"].variables == (
        "party_size",
        "date",
        "time",
        "area",
    )
    assert TEMPLATES["booking_reminder"].variables == TEMPLATES[
        "booking_confirmed"
    ].variables


# ── pure: retry with backoff ─────────────────────────────────────────────


async def test_send_with_retry_succeeds_after_failures():
    calls = {"n": 0}

    async def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise WhatsAppSendError("transient")
        return "wamid.FINAL"

    result = await send_with_retry(flaky, base_delay=0)
    assert result == "wamid.FINAL"
    assert calls["n"] == 3


async def test_send_with_retry_gives_up():
    calls = {"n": 0}

    async def always_fails() -> str:
        calls["n"] += 1
        raise WhatsAppSendError("nope")

    with pytest.raises(WhatsAppSendError):
        await send_with_retry(always_fails, attempts=3, base_delay=0)
    assert calls["n"] == 3  # bounded — never retries forever


# ── DB: transport delivery ───────────────────────────────────────────────


@pytest_asyncio.fixture
async def wa_thread():
    """Tenant + whatsapp channel + guest(phone) + conversation, no messages."""
    slug = f"wa-hard-{uuid.uuid4().hex[:8]}"
    ids: dict = {}
    async with SessionLocal() as s:
        t = Tenant(slug=slug, name="Hardening")
        s.add(t)
        await s.flush()
        ch = Channel(
            tenant_id=t.id, type=ChannelType.whatsapp, external_id="1000", active=True
        )
        s.add(ch)
        await s.flush()
        g = Guest(tenant_id=t.id, phone="15551234567", display_name="Chidera")
        s.add(g)
        await s.flush()
        conv = Conversation(
            tenant_id=t.id,
            channel_id=ch.id,
            channel_type=ChannelType.whatsapp,
            external_thread_id="15551234567",
            guest_id=g.id,
        )
        s.add(conv)
        await s.flush()
        ids["tenant_id"] = t.id
        ids["conv_id"] = conv.id
        await s.commit()
    yield ids
    async with SessionLocal() as s:
        t = await s.get(Tenant, ids["tenant_id"])
        if t:
            await s.delete(t)
            await s.commit()


async def _add_guest_message(conv_id, tenant_id, *, hours_ago: int) -> None:
    async with SessionLocal() as s:
        s.add(
            Message(
                tenant_id=tenant_id,
                conversation_id=conv_id,
                role=MessageRole.guest,
                content="book a table for 4",
                created_at=datetime.now(UTC) - timedelta(hours=hours_ago),
            )
        )
        await s.commit()


async def _add_confirmed_reservation(conv_id, tenant_id) -> None:
    async with SessionLocal() as s:
        s.add(
            Reservation(
                tenant_id=tenant_id,
                conversation_id=conv_id,
                party_size=4,
                date=datetime.now(UTC).date() + timedelta(days=2),
                time=datetime.now(UTC).time().replace(hour=20, minute=30, second=0),
                area="terrace",
                status=ReservationStatus.confirmed,
                idempotency_key=f"tpl-{uuid.uuid4().hex[:12]}",
            )
        )
        await s.commit()


async def _assistant_rows(conv_id) -> list[Message]:
    async with SessionLocal() as s:
        rows = (
            await s.execute(
                select(Message).where(
                    Message.conversation_id == conv_id,
                    Message.role == MessageRole.assistant,
                )
            )
        ).scalars().all()
        return rows


async def test_in_window_delivers_free_text(wa_thread):
    await _add_guest_message(wa_thread["conv_id"], wa_thread["tenant_id"], hours_ago=0)
    mock = MockWhatsAppClient()
    transport = WhatsAppTransport(mock)
    await transport.handle_event(
        NOTIF_MESSAGE_SENT,
        tenant_id=wa_thread["tenant_id"],
        payload={"message": "Your table is confirmed!", "channel_type": "whatsapp"},
    )
    assert len(mock.sent) == 1
    assert mock.sent[0]["kind"] == "text"
    assert mock.sent[0]["to"] == "15551234567"

    rows = await _assistant_rows(wa_thread["conv_id"])
    assert len(rows) == 1
    assert rows[0].meta["wa_message_id"]  # stamped for delivery receipts
    assert rows[0].meta["idempotency_key"]


async def test_out_of_window_uses_approved_template(wa_thread):
    await _add_guest_message(wa_thread["conv_id"], wa_thread["tenant_id"], hours_ago=25)
    await _add_confirmed_reservation(wa_thread["conv_id"], wa_thread["tenant_id"])
    mock = MockWhatsAppClient()
    transport = WhatsAppTransport(mock)
    await transport.handle_event(
        NOTIF_MESSAGE_SENT,
        tenant_id=wa_thread["tenant_id"],
        payload={"subject": "confirmation", "channel_type": "whatsapp"},
    )
    assert len(mock.sent) == 1
    sent = mock.sent[0]
    assert sent["kind"] == "template"
    assert sent["name"] == "booking_confirmed"
    assert sent["variables"]["party_size"] == "4"
    assert sent["variables"]["area"] == "terrace"


async def test_out_of_window_no_template_blocks_loudly(wa_thread):
    """A subject with no approved template ("survey") → blocked, never a silent
    drop. ("update" deliberately DOES resolve — to booking_updated.)"""
    await _add_guest_message(wa_thread["conv_id"], wa_thread["tenant_id"], hours_ago=25)
    mock = MockWhatsAppClient()
    transport = WhatsAppTransport(mock)
    await transport.handle_event(
        NOTIF_MESSAGE_SENT,
        tenant_id=wa_thread["tenant_id"],
        payload={"subject": "survey", "channel_type": "whatsapp"},
    )
    assert mock.sent == []  # nothing delivered
    rows = await _assistant_rows(wa_thread["conv_id"])
    assert len(rows) == 1
    assert rows[0].meta["delivery"] == {"failed": True, "reason": "blocked"}


async def test_retry_sends_exactly_once(wa_thread):
    await _add_guest_message(wa_thread["conv_id"], wa_thread["tenant_id"], hours_ago=0)
    mock = FlakyMockClient(failures=2)
    transport = WhatsAppTransport(mock)
    await transport.handle_event(
        NOTIF_MESSAGE_SENT,
        tenant_id=wa_thread["tenant_id"],
        payload={"message": "retry me", "channel_type": "whatsapp"},
    )
    assert mock.attempts == 3  # 2 failures + 1 success, bounded
    rows = await _assistant_rows(wa_thread["conv_id"])
    assert len(rows) == 1  # exactly one delivery, never doubled


async def test_renotify_does_not_double_send(wa_thread):
    await _add_guest_message(wa_thread["conv_id"], wa_thread["tenant_id"], hours_ago=0)
    mock = MockWhatsAppClient()
    transport = WhatsAppTransport(mock)
    payload = {"message": "once only", "channel_type": "whatsapp"}
    await transport.handle_event(
        NOTIF_MESSAGE_SENT, tenant_id=wa_thread["tenant_id"], payload=payload
    )
    # a re-notify (e.g. scheduler re-fire) must not send again
    await transport.handle_event(
        NOTIF_MESSAGE_SENT, tenant_id=wa_thread["tenant_id"], payload=payload
    )
    assert len(mock.sent) == 1
    rows = await _assistant_rows(wa_thread["conv_id"])
    assert len(rows) == 1


# ── DB: delivery receipts via webhook ────────────────────────────────────


def _sign(raw: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def _wa_headers(payload: dict, secret: str = SECRET) -> dict:
    raw = json.dumps(payload).encode()
    return {"content-type": "application/json", "X-Hub-Signature-256": _sign(raw, secret)}


def _patch_settings(monkeypatch, **overrides):
    base = {"WHATSAPP_APP_SECRET": SECRET, **overrides}
    monkeypatch.setattr(whatsapp_router, "get_settings", lambda: Settings(**base))


async def test_status_callback_persists_delivery_meta(wa_thread, monkeypatch):
    """sent → delivered → read transitions land on the outbound Message.meta."""
    _patch_settings(monkeypatch)
    async with SessionLocal() as s:
        s.add(
            Message(
                tenant_id=wa_thread["tenant_id"],
                conversation_id=wa_thread["conv_id"],
                role=MessageRole.assistant,
                content="hello",
                meta={"channel": "whatsapp", "wa_message_id": "wamid.STATUS1"},
            )
        )
        await s.commit()

    def _status_payload(state: str) -> dict:
        return {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "1",
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "statuses": [
                                    {
                                        "id": "wamid.STATUS1",
                                        "status": state,
                                        "timestamp": "1750000000",
                                    }
                                ],
                            },
                            "field": "messages",
                        }
                    ],
                }
            ],
        }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/webhooks/whatsapp",
            content=json.dumps(_status_payload("sent")),
            headers=_wa_headers(_status_payload("sent")),
        )
        assert r.status_code == 200
        r = await client.post(
            "/webhooks/whatsapp",
            content=json.dumps(_status_payload("delivered")),
            headers=_wa_headers(_status_payload("delivered")),
        )
        assert r.status_code == 200
        r = await client.post(
            "/webhooks/whatsapp",
            content=json.dumps(_status_payload("read")),
            headers=_wa_headers(_status_payload("read")),
        )
        assert r.status_code == 200

    async with SessionLocal() as s:
        row = (
            await s.execute(
                select(Message).where(Message.meta["wa_message_id"].astext == "wamid.STATUS1")
            )
        ).scalar_one()
        assert row.meta["delivery"]["sent"] == "1750000000"
        assert row.meta["delivery"]["delivered"] == "1750000000"
        assert row.meta["delivery"]["read"] == "1750000000"


class FlakyMockClient(MockWhatsAppClient):
    """Fails the first `failures` sends, then behaves like the normal mock."""

    def __init__(self, failures: int = 0) -> None:
        super().__init__()
        self._failures = failures
        self.attempts = 0

    async def send_text(self, *, to: str, body: str) -> str:
        self.attempts += 1
        if self.attempts <= self._failures:
            raise WhatsAppSendError("transient")
        return await super().send_text(to=to, body=body)

    async def send_template(self, *, to: str, name: str, variables: dict) -> str:
        self.attempts += 1
        if self.attempts <= self._failures:
            raise WhatsAppSendError("transient")
        return await super().send_template(to=to, name=name, variables=variables)
