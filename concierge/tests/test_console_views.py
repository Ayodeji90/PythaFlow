"""Day-17 staff console tests.

- Auth + page serving tests need no DB (the 401 fires before any query) —
  they run anywhere.
- List / transcript / SSE tests need Postgres (same pattern as the Day-15/16
  DB suites): run once `docker compose up -d db redis` + `alembic upgrade
  head` have been done (see HAND_OFF.md).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db import SessionLocal
from app.main import app
from app.models import Conversation, Guest, Message, Request, Tenant
from app.models.enums import ChannelType, MessageRole, RequestPriority, RequestStatus, RequestType
from app.routers.stream import _changed_conversation_ids

TOKEN = "console-test-token"


def _auth() -> dict:
    return {"X-Staff-Token": TOKEN}


# ── auth + page (no DB needed) ───────────────────────────────────────────


async def test_conversations_list_requires_token():
    # 401 fires before any DB work — this runs without Postgres. The
    # token-accepted path is covered by the DB suite below.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/conversations", params={"tenant": "demo"})
        assert r.status_code == 401


async def test_detail_requires_token():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/conversations/00000000-0000-0000-0000-000000000000",
                        params={"tenant": "demo"})
        assert r.status_code == 401


async def test_console_page_requires_token():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/console")
        assert r.status_code == 401
        r = await c.get(f"/console?token={TOKEN}")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "Staff Console" in r.text


# ── DB: list / transcript / SSE ──────────────────────────────────────────


@pytest_asyncio.fixture
async def console_data():
    """Two tenants with conversations, guests, messages and a linked Request."""
    now = datetime.now(UTC)
    async with SessionLocal() as s:
        ta = Tenant(slug=f"tenta-{uuid.uuid4().hex[:6]}", name="Tenant A")
        s.add(ta)
        await s.flush()
        tb = Tenant(slug=f"tentb-{uuid.uuid4().hex[:6]}", name="Tenant B")
        s.add(tb)
        await s.flush()

        ga = Guest(tenant_id=ta.id, display_name="Amara", phone="1111111")
        s.add(ga)
        await s.flush()
        gb = Guest(tenant_id=tb.id, display_name="Bola", phone="2222222")
        s.add(gb)
        await s.flush()

        ca = Conversation(
            tenant_id=ta.id, channel_type=ChannelType.whatsapp,
            external_thread_id="wa-1", guest_id=ga.id,
        )
        s.add(ca)
        await s.flush()
        cb = Conversation(
            tenant_id=tb.id, channel_type=ChannelType.webchat,
            external_thread_id="web-1", guest_id=gb.id,
        )
        s.add(cb)
        await s.flush()

        s.add(Message(
            tenant_id=ta.id, conversation_id=ca.id, role=MessageRole.guest,
            content="book a table for 4", created_at=now - timedelta(minutes=2),
        ))
        s.add(Message(
            tenant_id=ta.id, conversation_id=ca.id, role=MessageRole.assistant,
            content="8:30 works?",
            meta={"delivery": {"read": "1750000000"}},
            created_at=now - timedelta(minutes=1),
        ))
        s.add(Message(
            tenant_id=tb.id, conversation_id=cb.id, role=MessageRole.guest,
            content="do you cater for 30?", created_at=now,
        ))
        s.add(Request(
            tenant_id=ta.id, conversation_id=ca.id,
            type=RequestType.reservation, status=RequestStatus.needs_review,
            summary="Table for 4", priority=RequestPriority.normal,
            confidence=0.9,
        ))
        await s.commit()
        yield {
            "slug_a": ta.slug, "slug_b": tb.slug,
            "ca": ca.id, "cb": cb.id, "ta": ta.id, "tb": tb.id,
        }
    async with SessionLocal() as s:
        for tid in (ta.id, tb.id):
            t = await s.get(Tenant, tid)
            if t:
                await s.delete(t)
                await s.commit()


async def test_list_returns_only_caller_tenant(console_data):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/conversations", params={"tenant": console_data["slug_a"]},
                        headers=_auth())
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        row = data["conversations"][0]
        assert row["channel_type"] == "whatsapp"
        assert row["guest_name"] == "Amara"
        assert row["last_message_preview"] == "8:30 works?"
        assert row["unread"] == 0  # last message is the assistant's


async def test_list_channel_and_q_filters(console_data):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # channel filter on tenant A
        r = await c.get("/api/conversations",
                        params={"tenant": console_data["slug_a"], "channel": "whatsapp"},
                        headers=_auth())
        assert r.json()["total"] == 1
        r = await c.get("/api/conversations",
                        params={"tenant": console_data["slug_a"], "channel": "webchat"},
                        headers=_auth())
        assert r.json()["total"] == 0
        # q matches guest name (tenant B) and message content (tenant A)
        r = await c.get("/api/conversations",
                        params={"tenant": console_data["slug_b"], "q": "Bola"},
                        headers=_auth())
        assert r.json()["total"] == 1
        r = await c.get("/api/conversations",
                        params={"tenant": console_data["slug_a"], "q": "table"},
                        headers=_auth())
        assert r.json()["total"] == 1


async def test_detail_full_transcript_and_linked_request(console_data):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/api/conversations/{console_data['ca']}",
                        params={"tenant": console_data["slug_a"]}, headers=_auth())
        assert r.status_code == 200
        d = r.json()
        assert [m["role"] for m in d["messages"]] == ["guest", "assistant"]
        assert d["messages"][0]["content"] == "book a table for 4"
        assert d["messages"][1]["delivery_ticks"]["read"] == "1750000000"
        assert d["guest"]["display_name"] == "Amara"
        assert len(d["requests"]) == 1
        assert d["requests"][0]["type"] == "reservation"
        assert d["requests"][0]["status"] == "needs_review"


async def test_detail_cross_tenant_404(console_data):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/api/conversations/{console_data['cb']}",
                        params={"tenant": console_data["slug_a"]}, headers=_auth())
        assert r.status_code == 404
        r = await c.get(f"/api/conversations/{console_data['ca']}",
                        params={"tenant": console_data["slug_b"]}, headers=_auth())
        assert r.status_code == 404


async def test_stream_change_detection(console_data):
    """The SSE poll picks up conversations with a new message since the cursor."""
    since = datetime.now(UTC) - timedelta(hours=1)
    changed = await _changed_conversation_ids(console_data["ta"], since)
    assert str(console_data["ca"]) in changed
    # nothing new after `now` (updated_at server-side should be <= now)
    later = datetime.now(UTC) + timedelta(seconds=1)
    changed_later = await _changed_conversation_ids(console_data["ta"], later)
    assert str(console_data["ca"]) not in changed_later
