"""Day-3 proof: a message round-trips through the pipeline and both turns land in
the database under the right tenant + conversation."""
import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.channels.base import TenantNotFound, handle_inbound
from app.channels.webchat import WebChatAdapter
from app.db import SessionLocal
from app.main import app
from app.models import Conversation, Message, Tenant
from app.models.enums import MessageRole
from app.orchestrator.echo import EchoOrchestrator


async def test_echo_roundtrips_and_persists(session):
    tenant = Tenant(slug=f"t-{uuid.uuid4().hex[:8]}", name="Echo Test")
    session.add(tenant)
    await session.flush()

    conv_ref = uuid.uuid4().hex
    msg = WebChatAdapter.to_inbound(
        tenant_slug=tenant.slug, conversation_ref=conv_ref, content="Hello there"
    )

    chunks = [
        c
        async for c in handle_inbound(
            msg, db=session, redis=None, orchestrator=EchoOrchestrator()
        )
    ]

    # the echo came back
    types = [c.type for c in chunks]
    assert types == ["typing", "message", "done"]
    assert chunks[1].content == "You said: Hello there"

    # a conversation was created for this thread, scoped to the tenant
    conv = (
        await session.execute(
            select(Conversation).where(
                Conversation.tenant_id == tenant.id,
                Conversation.external_thread_id == conv_ref,
            )
        )
    ).scalar_one()

    # both turns persisted, in order, under the right tenant + conversation
    rows = (
        await session.execute(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at)
        )
    ).scalars().all()
    assert [r.role for r in rows] == [MessageRole.guest, MessageRole.assistant]
    assert rows[0].content == "Hello there"
    assert rows[1].content == "You said: Hello there"
    assert all(r.tenant_id == tenant.id for r in rows)


async def test_same_thread_reuses_conversation(session):
    tenant = Tenant(slug=f"t-{uuid.uuid4().hex[:8]}", name="Thread Test")
    session.add(tenant)
    await session.flush()
    conv_ref = uuid.uuid4().hex

    for text in ("first", "second"):
        msg = WebChatAdapter.to_inbound(
            tenant_slug=tenant.slug, conversation_ref=conv_ref, content=text
        )
        async for _ in handle_inbound(
            msg, db=session, redis=None, orchestrator=EchoOrchestrator()
        ):
            pass

    convs = (
        await session.execute(
            select(Conversation).where(Conversation.tenant_id == tenant.id)
        )
    ).scalars().all()
    assert len(convs) == 1  # same thread ref -> one conversation

    rows = (
        await session.execute(
            select(Message).where(Message.conversation_id == convs[0].id)
        )
    ).scalars().all()
    assert len(rows) == 4  # 2 guest + 2 assistant


async def test_unknown_tenant_raises(session):
    msg = WebChatAdapter.to_inbound(
        tenant_slug="does-not-exist", conversation_ref="x", content="hi"
    )
    try:
        async for _ in handle_inbound(
            msg, db=session, redis=None, orchestrator=EchoOrchestrator()
        ):
            pass
        raise AssertionError("expected TenantNotFound")
    except TenantNotFound:
        pass


# --- the REST endpoint, end to end through the router ------------------------


@pytest_asyncio.fixture
async def live_tenant():
    """A committed tenant for endpoint tests (the app uses its own session).
    Deleted afterwards — the tenant_id CASCADE cleans up conversations/messages."""
    slug = f"api-{uuid.uuid4().hex[:8]}"
    async with SessionLocal() as s:
        t = Tenant(slug=slug, name="API Test")
        s.add(t)
        await s.commit()
        tid = t.id
    yield slug
    async with SessionLocal() as s:
        t = await s.get(Tenant, tid)
        if t:
            await s.delete(t)
            await s.commit()


async def test_api_chat_endpoint(live_tenant):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/chat", json={"tenant": live_tenant, "content": "ping"})
        assert r.status_code == 200
        body = r.json()
        assert body["reply"] == "You said: ping"
        assert body["conversation_ref"]

        # unknown tenant -> 404
        r404 = await client.post("/api/chat", json={"tenant": "nope-nope", "content": "x"})
        assert r404.status_code == 404
