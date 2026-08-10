"""Day-19 escalation tests.

The rule evaluation is pure (runs anywhere); the DB/service/subscriber tests
need Postgres (see HAND_OFF.md).
"""
from __future__ import annotations

import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.deps import get_db
from app.main import app
from app.models import Conversation, Guest, Request, Tenant
from app.models.enums import (
    ChannelType,
    ConversationStatus,
    RequestPriority,
    RequestStatus,
    RequestType,
)
from app.notifications import NOTIF_ESCALATED, register_subscriber
from app.notifications.email import EmailSubscriber
from app.notifications.slack import SlackSubscriber
from app.orchestrator.escalation import evaluate_reasons, maybe_escalate

SETTINGS = get_settings()


def _req(**kw):
    return Request(
        tenant_id=uuid.uuid4(),
        type=kw.get("type", RequestType.enquiry),
        status=RequestStatus.needs_review,
        priority=kw.get("priority", RequestPriority.normal),
        confidence=kw.get("confidence", 0.95),
        summary=kw.get("summary", "x"),
        payload={},
    )


def _guest(vip=False):
    return Guest(
        tenant_id=uuid.uuid4(),
        phone="1",
        preferences={"vip": True} if vip else {},
    )


# ── pure: rule evaluation ────────────────────────────────────────────────


async def test_reason_low_confidence():
    reasons = evaluate_reasons(request=_req(confidence=0.5), guest=None, message="hi",
                               settings=SETTINGS)
    assert "low_confidence" in reasons


async def test_no_low_confidence_above_threshold():
    reasons = evaluate_reasons(request=_req(confidence=0.95), guest=None, message="hi",
                               settings=SETTINGS)
    assert "low_confidence" not in reasons


async def test_reason_complaint():
    reasons = evaluate_reasons(request=_req(type=RequestType.complaint), guest=None,
                               message="food was awful", settings=SETTINGS)
    assert "complaint" in reasons


async def test_reason_vip():
    reasons = evaluate_reasons(request=_req(), guest=_guest(vip=True), message="hi",
                               settings=SETTINGS)
    assert "vip" in reasons
    reasons = evaluate_reasons(request=_req(), guest=_guest(), message="hi",
                               settings=SETTINGS)
    assert "vip" not in reasons


async def test_reason_explicit_ask():
    reasons = evaluate_reasons(request=None, guest=None, message="let me speak to a manager",
                               settings=SETTINGS)
    assert "explicit_ask" in reasons
    reasons = evaluate_reasons(request=None, guest=None, message="what time do you close?",
                               settings=SETTINGS)
    assert reasons == []


async def test_reasons_combine():
    reasons = evaluate_reasons(
        request=_req(type=RequestType.complaint, confidence=0.5),
        guest=_guest(vip=True),
        message="talk to a human",
        settings=SETTINGS,
    )
    assert set(reasons) == {"complaint", "low_confidence", "vip", "explicit_ask"}


# ── DB: maybe_escalate applies state + notifies ──────────────────────────


class Recorder:
    def __init__(self) -> None:
        self.events: list = []

    async def handle_event(self, event, *, tenant_id, request_id=None, payload=None):
        self.events.append((event, tenant_id, request_id, payload))


@pytest_asyncio.fixture
async def escalation_setup(session):
    tenant = Tenant(slug=f"esc-{uuid.uuid4().hex[:8]}", name="Escalate")
    session.add(tenant)
    await session.flush()
    conv = Conversation(tenant_id=tenant.id, channel_type=ChannelType.webchat)
    session.add(conv)
    await session.flush()
    request = Request(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        type=RequestType.enquiry,
        status=RequestStatus.needs_review,
        summary="Something needs review",
        payload={},
        confidence=0.5,  # below REQUEST_REVIEW_CONFIDENCE (0.75)
        priority=RequestPriority.normal,
    )
    session.add(request)
    await session.flush()
    await session.commit()
    return tenant, conv, request


async def test_maybe_escalate_flags_bumps_notifies(session, escalation_setup):
    tenant, conv, request = escalation_setup
    rec = Recorder()
    register_subscriber(NOTIF_ESCALATED, rec.handle_event)

    reasons = await maybe_escalate(
        session, tenant=tenant, conversation=conv, guest=None,
        request=request, message="hi",
    )
    assert reasons == ["low_confidence"]
    await session.refresh(conv)
    await session.refresh(request)
    assert conv.status == ConversationStatus.human
    assert request.priority == RequestPriority.high
    assert len(rec.events) == 1
    assert rec.events[0][0] == NOTIF_ESCALATED


async def test_maybe_escalate_disabled_by_tenant_config(session, escalation_setup):
    tenant, conv, request = escalation_setup
    tenant.config = {"escalation": {"enabled": False}}
    await session.commit()
    rec = Recorder()
    register_subscriber(NOTIF_ESCALATED, rec.handle_event)

    reasons = await maybe_escalate(
        session, tenant=tenant, conversation=conv, guest=None,
        request=request, message="hi",
    )
    assert reasons == []
    await session.refresh(conv)
    assert conv.status != ConversationStatus.human
    assert rec.events == []


async def test_maybe_escalate_no_renotify_when_already_human(session, escalation_setup):
    tenant, conv, request = escalation_setup
    rec = Recorder()
    register_subscriber(NOTIF_ESCALATED, rec.handle_event)

    await maybe_escalate(session, tenant=tenant, conversation=conv, guest=None,
                         request=request, message="hi")
    assert len(rec.events) == 1
    # a second turn in an already-escalated conversation must not spam alerts
    await maybe_escalate(session, tenant=tenant, conversation=conv, guest=None,
                         request=request, message="still need help")
    assert len(rec.events) == 1


# ── subscribers ──────────────────────────────────────────────────────────


class FakePost:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, url: str, text: str) -> None:
        self.calls.append((url, text))


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_reply(self, *, to, subject, body, in_reply_to=None, tenant_config=None):
        self.sent.append({"to": to, "subject": subject, "body": body})
        return "<test-id>"


async def test_slack_subscriber_posts_to_tenant_webhook(session):
    tenant = Tenant(slug=f"slack-{uuid.uuid4().hex[:8]}", name="Slack", config={
        "notify": {"slack": "https://hooks.slack.com/fake"}
    })
    session.add(tenant)
    await session.flush()
    await session.commit()

    post = FakePost()
    sub = SlackSubscriber(post=post)
    await sub.handle_event(
        NOTIF_ESCALATED,
        tenant_id=tenant.id,
        payload={"summary": "Complaint about food", "reason": ["complaint"]},
    )
    assert len(post.calls) == 1
    url, text = post.calls[0]
    assert url == "https://hooks.slack.com/fake"
    assert "Complaint about food" in text
    assert "complaint" in text


async def test_slack_subscriber_silent_without_webhook(session):
    tenant = Tenant(slug=f"slack-{uuid.uuid4().hex[:8]}", name="No Slack")
    session.add(tenant)
    await session.flush()
    await session.commit()

    post = FakePost()
    await SlackSubscriber(post=post).handle_event(
        NOTIF_ESCALATED, tenant_id=tenant.id, payload={}
    )
    assert post.calls == []


async def test_email_subscriber_sends_to_tenant_recipients(session):
    tenant = Tenant(slug=f"mail-{uuid.uuid4().hex[:8]}", name="Mail", config={
        "notify": {"email": ["manager@venue.com", "owner@venue.com"]}
    })
    session.add(tenant)
    await session.flush()
    await session.commit()

    sender = FakeSender()
    await EmailSubscriber(sender=sender).handle_event(
        NOTIF_ESCALATED, tenant_id=tenant.id,
        payload={"summary": "VIP is unhappy", "reason": ["vip", "complaint"]},
    )
    assert {s["to"] for s in sender.sent} == {"manager@venue.com", "owner@venue.com"}
    assert "VIP is unhappy" in sender.sent[0]["subject"]


# ── handoff: escalated conversation surfaces in the needs-human inbox ─────


async def test_escalated_conversation_in_needs_human_inbox(session, escalation_setup):
    tenant, conv, request = escalation_setup
    await maybe_escalate(session, tenant=tenant, conversation=conv, guest=None,
                         request=request, message="hi")

    async def _override():
        yield session

    app.dependency_overrides[get_db] = _override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/conversations",
                            params={"tenant": tenant.slug, "status": "human"},
                            headers={"X-Staff-Token": "t"})
            assert r.status_code == 200
            rows = r.json()["conversations"]
            assert any(row["id"] == str(conv.id) for row in rows)
    finally:
        app.dependency_overrides.clear()
