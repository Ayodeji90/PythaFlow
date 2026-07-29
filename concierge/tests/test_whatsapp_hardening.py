"""Day 16 — WhatsApp hardening tests: 24h session window, send retry+idempotency,
templates, and delivery-receipt status updates. No network."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.channels.whatsapp import (
    NullWhatsAppClient,
    send_with_retry,
    session_window_open,
)
from app.models import Conversation, Message, Tenant
from app.models.enums import ChannelType, MessageRole
from app.routers.whatsapp import _apply_status, _record_outbound_sid


async def _conv_with_inbound(session, *, age_hours: float | None):
    tenant = Tenant(slug=f"wa-{uuid.uuid4().hex[:8]}", name="WA")
    session.add(tenant)
    await session.flush()
    conv = Conversation(
        tenant_id=tenant.id,
        channel_type=ChannelType.whatsapp,
        external_thread_id=uuid.uuid4().hex,
    )
    session.add(conv)
    await session.flush()
    if age_hours is not None:
        session.add(
            Message(
                tenant_id=tenant.id,
                conversation_id=conv.id,
                role=MessageRole.guest,
                content="hi",
                created_at=datetime.now(UTC) - timedelta(hours=age_hours),
            )
        )
        await session.flush()
    return tenant, conv


# ── 24-hour session window ────────────────────────────────────────────────


async def test_window_open_within_24h(session):
    _, conv = await _conv_with_inbound(session, age_hours=1)
    assert await session_window_open(session, conv.id, hours=24) is True


async def test_window_closed_after_24h(session):
    _, conv = await _conv_with_inbound(session, age_hours=25)
    assert await session_window_open(session, conv.id, hours=24) is False


async def test_window_closed_with_no_inbound(session):
    _, conv = await _conv_with_inbound(session, age_hours=None)
    assert await session_window_open(session, conv.id, hours=24) is False


# ── Outbound send: retry + never-double-send ──────────────────────────────


async def test_send_with_retry_success_once():
    calls = []

    async def ok():
        calls.append(1)
        return "sid-ok"

    assert await send_with_retry(ok, max_retries=3, base_delay=0) == "sid-ok"
    assert len(calls) == 1  # a success is sent exactly once


async def test_send_with_retry_recovers_from_transient():
    state = {"n": 0}

    async def flaky():
        state["n"] += 1
        if state["n"] < 2:
            raise RuntimeError("transient")
        return "sid-recovered"

    assert await send_with_retry(flaky, max_retries=3, base_delay=0) == "sid-recovered"
    assert state["n"] == 2


async def test_send_with_retry_gives_up_loudly():
    async def always_fail():
        raise RuntimeError("permanent")

    with pytest.raises(RuntimeError):
        await send_with_retry(always_fail, max_retries=2, base_delay=0)


# ── Templates ─────────────────────────────────────────────────────────────


async def test_null_client_send_template():
    sid = await NullWhatsAppClient().send_template(
        to="whatsapp:+2348012345678",
        content_sid="HX0123456789",
        variables={"1": "Ada", "2": "8:30pm"},
    )
    assert sid == "null-whatsapp-template"


# ── Delivery/read receipts ────────────────────────────────────────────────


async def test_receipt_status_flows_onto_message(session):
    tenant = Tenant(slug=f"wa-{uuid.uuid4().hex[:8]}", name="WA")
    session.add(tenant)
    await session.flush()
    conv = Conversation(
        tenant_id=tenant.id,
        channel_type=ChannelType.whatsapp,
        external_thread_id="234000111",
    )
    session.add(conv)
    await session.flush()
    msg = Message(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        role=MessageRole.assistant,
        content="Booked — table for 2 at 8:30pm.",
    )
    session.add(msg)
    await session.flush()

    # After sending, the sid is stamped on the assistant turn.
    await _record_outbound_sid(session, tenant.id, "234000111", "SMabc123")
    await session.refresh(msg)
    assert msg.meta["whatsapp_sid"] == "SMabc123"
    assert msg.meta["whatsapp_status"] == "sent"

    # A later receipt updates the status.
    await _apply_status(session, "SMabc123", "delivered")
    await session.refresh(msg)
    assert msg.meta["whatsapp_status"] == "delivered"
