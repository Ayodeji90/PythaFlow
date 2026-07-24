"""Email adapter tests — mirror the webchat test pattern exactly.

Tests use the `session` fixture (transaction-rolled-back per test) and the
`EchoOrchestrator` — no network, no LLM, deterministic assertions."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.channels.base import TenantNotFound, handle_inbound
from app.channels.email import (
    EmailAdapter,
    NullSender,
    ParsedEmail,
    SmtpSender,
)
from app.models import Conversation, Message, Tenant
from app.models.enums import MessageRole
from app.orchestrator.echo import EchoOrchestrator


def _make_email(
    *,
    message_id: str | None = None,
    in_reply_to: str | None = None,
    subject: str = "Dinner reservation",
    body: str = "Hi, I'd like a table for 2 at 7pm.",
    from_email: str = "guest@example.com",
    from_name: str | None = "Jane Guest",
    to_email: str = "demo-bistro@pythaflow.local",
) -> ParsedEmail:
    return ParsedEmail(
        message_id=message_id or f"<{uuid.uuid4().hex}@example.com>",
        in_reply_to=in_reply_to,
        subject=subject,
        body=body,
        from_email=from_email,
        from_name=from_name,
        to_email=to_email,
        date=datetime.now(UTC),
    )


# ── Unit: adapter ─────────────────────────────────────────────────────────


async def test_email_to_inbound_creates_correct_message():
    email = _make_email(body="Table for 2 please")
    msg = EmailAdapter.to_inbound(email, tenant_slug="demo")

    assert msg.tenant_slug == "demo"
    assert msg.channel.value == "email"
    assert msg.conversation_ref == email.message_id
    assert msg.sender.id == "guest@example.com"
    assert msg.sender.name == "Jane Guest"
    assert msg.content == "Table for 2 please"
    assert msg.metadata["source"] == "email"
    assert msg.metadata["email"]["subject"] == "Dinner reservation"
    assert msg.metadata["email"]["to_email"] == "demo-bistro@pythaflow.local"


async def test_email_thread_ref_uses_in_reply_to():
    parent_id = "<parent@example.com>"
    child = _make_email(message_id="<child@example.com>", in_reply_to=parent_id)
    msg = EmailAdapter.to_inbound(child, tenant_slug="demo")

    # A reply reuses the parent's thread ID so it lands in the same Conversation.
    assert msg.conversation_ref == parent_id


async def test_email_missing_body_falls_back_to_subject():
    email = _make_email(body="", subject="Booking inquiry")
    msg = EmailAdapter.to_inbound(email, tenant_slug="demo")
    assert msg.content == "Booking inquiry"


async def test_email_sender_id_uses_from_email():
    email = _make_email(from_email="guest@example.com", from_name=None)
    msg = EmailAdapter.to_inbound(email, tenant_slug="demo")
    assert msg.sender.id == "guest@example.com"
    assert msg.sender.name is None


# ── Pipeline: round-trip ──────────────────────────────────────────────────


async def test_email_roundtrips_and_persists(session):
    tenant = Tenant(slug=f"email-t-{uuid.uuid4().hex[:8]}", name="Email Test")
    session.add(tenant)
    await session.flush()

    email = _make_email(body="What are your hours?")
    msg = EmailAdapter.to_inbound(email, tenant_slug=tenant.slug)

    chunks = [
        c
        async for c in handle_inbound(
            msg, db=session, redis=None, orchestrator=EchoOrchestrator()
        )
    ]

    types = [c.type for c in chunks]
    assert types == ["typing", "message", "done"]
    assert chunks[1].content == "You said: What are your hours?"

    # Conversation was created for this email thread, scoped to the tenant.
    conv = (
        await session.execute(
            select(Conversation).where(
                Conversation.tenant_id == tenant.id,
                Conversation.external_thread_id == email.message_id,
            )
        )
    ).scalar_one()

    # Both turns persisted, in order.
    rows = (
        await session.execute(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at)
        )
    ).scalars().all()
    assert [r.role for r in rows] == [MessageRole.guest, MessageRole.assistant]
    assert rows[0].content == "What are your hours?"
    assert rows[1].content == "You said: What are your hours?"
    assert all(r.tenant_id == tenant.id for r in rows)


# ── Pipeline: threading ────────────────────────────────────────────────────


async def test_email_reply_reuses_same_conversation(session):
    tenant = Tenant(slug=f"email-t-{uuid.uuid4().hex[:8]}", name="Thread Test")
    session.add(tenant)
    await session.flush()

    parent_id = f"<parent-{uuid.uuid4().hex}@example.com>"

    # First email — brand new thread.
    email1 = _make_email(message_id=parent_id, body="I'd like to book a table")
    msg1 = EmailAdapter.to_inbound(email1, tenant_slug=tenant.slug)
    async for _ in handle_inbound(
        msg1, db=session, redis=None, orchestrator=EchoOrchestrator()
    ):
        pass

    # Reply — same thread, references the parent.
    email2 = _make_email(
        message_id=f"<child-{uuid.uuid4().hex}@example.com>",
        in_reply_to=parent_id,
        body="Actually, make it 8pm",
    )
    msg2 = EmailAdapter.to_inbound(email2, tenant_slug=tenant.slug)
    async for _ in handle_inbound(
        msg2, db=session, redis=None, orchestrator=EchoOrchestrator()
    ):
        pass

    # Only one Conversation for this thread.
    convs = (
        await session.execute(
            select(Conversation).where(Conversation.tenant_id == tenant.id)
        )
    ).scalars().all()
    assert len(convs) == 1

    # 4 messages: 2 guest + 2 assistant.
    # All created_at are identical (same transaction), and UUIDs are random,
    # so assert by content presence rather than positional ordering.
    rows = (
        await session.execute(
            select(Message).where(Message.conversation_id == convs[0].id)
        )
    ).scalars().all()
    contents = [r.content for r in rows]
    assert len(contents) == 4
    assert "I'd like to book a table" in contents
    assert "You said: I'd like to book a table" in contents
    assert "Actually, make it 8pm" in contents
    assert "You said: Actually, make it 8pm" in contents
    # Two guest turns + two assistant turns.
    roles = [r.role for r in rows]
    assert roles.count(MessageRole.guest) == 2
    assert roles.count(MessageRole.assistant) == 2


# ── Pipeline: unknown tenant ───────────────────────────────────────────────


async def test_email_unknown_tenant_raises(session):
    # The adapter doesn't validate the tenant — the pipeline does.
    msg = EmailAdapter.to_inbound(
        _make_email(to_email="unknown@venue.com"), tenant_slug="does-not-exist"
    )
    try:
        async for _ in handle_inbound(
            msg, db=session, redis=None, orchestrator=EchoOrchestrator()
        ):
            pass
        raise AssertionError("expected TenantNotFound")
    except TenantNotFound:
        pass


# ── Outbound sender (unit) ────────────────────────────────────────────────


async def test_null_sender_logs_and_returns():
    sender = NullSender()
    outbound_id = await sender.send_reply(
        to="guest@example.com",
        subject="Re: Dinner reservation",
        body="Thanks for your message!",
    )
    assert outbound_id == "<null-sender@local>"


async def test_smtp_sender_builds_headers():
    """Verify the SmtpSender constructs correct MIME headers without
    actually connecting to an SMTP server."""
    from unittest.mock import patch

    sender = SmtpSender(
        host="localhost", port=587, from_address="concierge@test.local", from_name="Test"
    )

    with patch("aiosmtplib.send") as mock_send:
        outbound_id = await sender.send_reply(
            to="guest@example.com",
            subject="Re: Booking",
            body="Hello!",
            in_reply_to="<original@test.local>",
        )

        # aiosmtplib.send was called with a MIMEText message
        call_args, call_kwargs = mock_send.call_args
        msg = call_args[0]
        assert msg["From"] == "Test <concierge@test.local>"
        assert msg["To"] == "guest@example.com"
        assert msg["Subject"] == "Re: Booking"
        assert msg["In-Reply-To"] == "<original@test.local>"
        assert msg["Message-ID"] == outbound_id
        assert call_kwargs["hostname"] == "localhost"
        assert call_kwargs["port"] == 587