"""Day-18 tests: console actions — edit-before-approve, human takeover,
staff sends, and the audit trail.

Auth 401s run anywhere; the rest need Postgres (same as the Day-15/16/17 DB
suites — see HAND_OFF.md).
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.channels.base import handle_inbound
from app.channels.webchat import WebChatAdapter
from app.channels.whatsapp.client import MockWhatsAppClient
from app.channels.whatsapp.transport import WhatsAppTransport
from app.deps import get_db
from app.main import app
from app.models import Action, Channel, Conversation, Guest, Message, Reservation, Tenant
from app.models.enums import (
    ChannelType,
    MessageRole,
    RequestPriority,
    RequestStatus,
    RequestType,
    ReservationStatus,
)
from app.models.request import Request
from app.notifications import NOTIF_MESSAGE_SENT, register_subscriber
from app.schemas.message import OutboundChunk

TOKEN = "console-actions-token"


async def _seed_request(session, *, channel_type=ChannelType.webchat) -> Request:
    """Tenant + webchat conversation + a pending reservation Request."""
    tenant = Tenant(slug=f"act-{uuid.uuid4().hex[:8]}", name="Actions")
    session.add(tenant)
    await session.flush()
    conv = Conversation(tenant_id=tenant.id, channel_type=channel_type)
    session.add(conv)
    await session.flush()
    request = Request(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        channel_type=channel_type,
        type=RequestType.reservation,
        status=RequestStatus.needs_review,
        summary="Table for 4 on 2026-08-01 at 20:00",
        payload={
            "date": "2026-08-01",
            "time": "20:00",
            "party_size": 4,
            "idempotency_key": f"key-{uuid.uuid4().hex[:10]}",
        },
        confidence=0.95,
        priority=RequestPriority.normal,
    )
    session.add(request)
    await session.flush()
    return request


class RecordingOrchestrator:
    """Fails the test loudly if the AI is ever invoked."""

    name = "recording"

    def __init__(self) -> None:
        self.calls = 0

    async def handle(self, msg, *, ctx, db, redis):  # noqa: ARG002 - test stub
        self.calls += 1
        yield OutboundChunk(type="message", content="AI SHOULD NOT HAVE REPLIED")


# ── auth (no DB needed) ──────────────────────────────────────────────────


async def test_takeover_requires_token():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/conversations/00000000-0000-0000-0000-000000000000/takeover",
                         params={"tenant": "demo"})
        assert r.status_code == 401


async def test_staff_message_requires_token():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/conversations/00000000-0000-0000-0000-000000000000/staff-message",
                         params={"tenant": "demo"}, json={"content": "hi"})
        assert r.status_code == 401


async def test_edit_requires_token():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.patch("/api/requests/00000000-0000-0000-0000-000000000000",
                          params={"tenant": "demo"}, json={"party_size": 6})
        assert r.status_code == 401


# ── DB: edit → approve → fulfilled with corrected payload ────────────────


@pytest_asyncio.fixture
async def client_session(session):
    """Session-backed ASGI client (dependency override) for endpoint tests."""

    async def _override():
        yield session

    app.dependency_overrides[get_db] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, session
    app.dependency_overrides.clear()


async def test_edit_then_approve_fulfils_corrected_payload(client_session):
    c, session = client_session
    request = await _seed_request(session)
    tenant = await session.get(Tenant, request.tenant_id)

    # staff fix the party size the AI misheard
    r = await c.patch(
        f"/api/requests/{request.id}",
        params={"tenant": tenant.slug},
        headers={"X-Staff-Token": TOKEN},
        json={"party_size": 6},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["payload"]["party_size"] == 6

    await session.refresh(request)
    assert request.payload["party_size"] == 6
    assert request.resolution["edited"]["party_size"] == 6  # never a silent edit
    assert request.resolution["edited_by"].startswith("staff:")

    # approve → fulfilment must write the CORRECTED values
    r = await c.post(
        "/api/approvals/decide",
        headers={"X-Staff-Token": TOKEN},
        json={"request_id": str(request.id), "decision": "approved"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "fulfilled"

    reservation = (
        await session.execute(
            select(Reservation).where(Reservation.tenant_id == tenant.id)
        )
    ).scalar_one()
    assert reservation.party_size == 6
    assert reservation.date == date(2026, 8, 1)
    assert reservation.status == ReservationStatus.confirmed

    # every mutation is audited
    audit = (
        await session.execute(
            select(Action).where(
                Action.tenant_id == tenant.id,
                Action.type.in_(["console.edit", "console.approve"]),
            )
        )
    ).scalars().all()
    assert {a.type for a in audit} == {"console.edit", "console.approve"}


async def test_edit_rejected_for_non_pending(client_session):
    c, session = client_session
    request = await _seed_request(session)
    tenant = await session.get(Tenant, request.tenant_id)
    request.status = RequestStatus.approved
    await session.flush()

    r = await c.patch(
        f"/api/requests/{request.id}",
        params={"tenant": tenant.slug},
        headers={"X-Staff-Token": TOKEN},
        json={"time": "19:30"},
    )
    assert r.status_code == 400


# ── DB: takeover pauses the AI, resume restores it ───────────────────────


async def test_takeover_pauses_ai_and_staff_send_delivers(client_session):
    c, session = client_session
    tenant = Tenant(slug=f"take-{uuid.uuid4().hex[:8]}", name="Takeover")
    session.add(tenant)
    await session.flush()
    channel = Channel(
        tenant_id=tenant.id, type=ChannelType.whatsapp, external_id="1000", active=True
    )
    session.add(channel)
    await session.flush()
    guest = Guest(tenant_id=tenant.id, phone="15551234567", display_name="Chidera")
    session.add(guest)
    await session.flush()
    conv = Conversation(
        tenant_id=tenant.id,
        channel_id=channel.id,
        channel_type=ChannelType.whatsapp,
        external_thread_id="15551234567",
        guest_id=guest.id,
    )
    session.add(conv)
    await session.flush()
    await session.commit()

    # staff take over
    r = await c.post(
        f"/api/conversations/{conv.id}/takeover",
        params={"tenant": tenant.slug},
        headers={"X-Staff-Token": TOKEN},
    )
    assert r.status_code == 200
    await session.refresh(conv)
    assert conv.status.value == "human"

    # a guest message now hits the pipeline → the AI must NOT run
    recording = RecordingOrchestrator()
    msg = WebChatAdapter.to_inbound(
        tenant_slug=tenant.slug, conversation_ref="15551234567", content="hello?"
    )
    chunks = [
        chunk
        async for chunk in handle_inbound(msg, db=session, redis=None, orchestrator=recording)
    ]
    assert recording.calls == 0  # brain stood down
    assert any("paused" in (chunk.content or "").lower() for chunk in chunks)

    # a staff reply delivers over WhatsApp via the notify() transport
    mock = MockWhatsAppClient()
    register_subscriber(NOTIF_MESSAGE_SENT, WhatsAppTransport(mock).handle_event)
    r = await c.post(
        f"/api/conversations/{conv.id}/staff-message",
        params={"tenant": tenant.slug},
        headers={"X-Staff-Token": TOKEN},
        json={"content": "Hi Chidera — we've reserved 8:30 for you."},
    )
    assert r.status_code == 200
    assert len(mock.sent) == 1
    assert mock.sent[0]["kind"] == "text"
    assert mock.sent[0]["to"] == "15551234567"

    staff_rows = (
        (
            await session.execute(
                select(Message).where(
                    Message.conversation_id == conv.id, Message.role == MessageRole.staff
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(staff_rows) == 1  # persisted as staff, not duplicated by the transport


async def test_resume_restores_ai(client_session):
    c, session = client_session
    tenant = Tenant(slug=f"res-{uuid.uuid4().hex[:8]}", name="Resume")
    session.add(tenant)
    await session.flush()
    conv = Conversation(tenant_id=tenant.id, channel_type=ChannelType.webchat)
    session.add(conv)
    await session.flush()
    await session.commit()

    await c.post(f"/api/conversations/{conv.id}/takeover", params={"tenant": tenant.slug},
                 headers={"X-Staff-Token": TOKEN})
    await session.refresh(conv)
    assert conv.status.value == "human"

    r = await c.post(f"/api/conversations/{conv.id}/resume", params={"tenant": tenant.slug},
                     headers={"X-Staff-Token": TOKEN})
    assert r.status_code == 200
    await session.refresh(conv)
    assert conv.status.value == "active"

    # the AI answers again
    recording = RecordingOrchestrator()
    msg = WebChatAdapter.to_inbound(
        tenant_slug=tenant.slug, conversation_ref="res-1", content="hi"
    )
    parts: list[str] = []
    async for chunk in handle_inbound(msg, db=session, redis=None, orchestrator=recording):
        if chunk.content and chunk.type in ("token", "message"):
            parts.append(chunk.content)
    assert recording.calls == 1  # brain is back


async def test_approvals_list_includes_channel_and_guest(client_session):
    c, session = client_session
    tenant = Tenant(slug=f"q-{uuid.uuid4().hex[:8]}", name="Queue")
    session.add(tenant)
    await session.flush()
    guest = Guest(tenant_id=tenant.id, display_name="Ada", phone="333")
    session.add(guest)
    await session.flush()
    request = Request(
        tenant_id=tenant.id,
        channel_type=ChannelType.whatsapp,
        guest_id=guest.id,
        type=RequestType.reservation,
        status=RequestStatus.needs_review,
        summary="Ada's table",
        payload={"date": "2026-08-02", "party_size": 2},
        confidence=0.9,
    )
    session.add(request)
    await session.flush()

    r = await c.get("/api/approvals", params={"tenant": tenant.slug},
                    headers={"X-Staff-Token": TOKEN})
    assert r.status_code == 200
    item = r.json()["requests"][0]
    assert item["channel_type"] == "whatsapp"
    assert item["guest_name"] == "Ada"
