"""WhatsApp (Twilio) adapter tests — mirror the email adapter pattern.

Pure-unit tests for parsing/mapping/signature + a pipeline test through the same
`handle_inbound` with the EchoOrchestrator (no network, no LLM). Proves the
"zero brain change" claim: WhatsApp rides the exact shared pipeline."""
from __future__ import annotations

import base64
import hashlib
import hmac
import uuid

from sqlalchemy import select

from app.channels.base import handle_inbound
from app.channels.whatsapp import (
    NullWhatsAppClient,
    TwilioWhatsAppClient,
    WhatsAppAdapter,
    WhatsAppInbound,
    build_whatsapp_client,
    validate_twilio_signature,
)
from app.config import Settings
from app.models import Conversation, Message, Tenant
from app.models.enums import ChannelType, MessageRole
from app.orchestrator.echo import EchoOrchestrator

_TWILIO_FORM = {
    "From": "whatsapp:+2348012345678",
    "To": "whatsapp:+14155238886",
    "Body": "Any tables for two tonight?",
    "WaId": "2348012345678",
    "ProfileName": "Ada N.",
    "MessageSid": "SM0123456789",
}


# ── Unit: inbound parsing + mapping ───────────────────────────────────────


def test_from_twilio_form_parses_fields():
    inbound = WhatsAppInbound.from_twilio_form(_TWILIO_FORM)
    assert inbound.from_number == "whatsapp:+2348012345678"
    assert inbound.to_number == "whatsapp:+14155238886"
    assert inbound.body == "Any tables for two tonight?"
    assert inbound.wa_id == "2348012345678"
    assert inbound.profile_name == "Ada N."
    assert inbound.message_sid == "SM0123456789"


def test_wa_id_falls_back_to_from_number():
    inbound = WhatsAppInbound.from_twilio_form(
        {"From": "whatsapp:+2348099999999", "Body": "hi"}
    )
    assert inbound.wa_id == "2348099999999"


def test_to_inbound_maps_to_canonical_message():
    inbound = WhatsAppInbound.from_twilio_form(_TWILIO_FORM)
    msg = WhatsAppAdapter.to_inbound(inbound, tenant_slug="demo")

    assert msg.tenant_slug == "demo"
    assert msg.channel == ChannelType.whatsapp
    assert msg.conversation_ref == "2348012345678"          # stable per-guest thread
    assert msg.sender.id == "2348012345678"
    assert msg.sender.name == "Ada N."
    assert msg.sender.phone == "+2348012345678"             # what lets guest_memory match
    assert msg.content == "Any tables for two tonight?"
    assert msg.metadata["source"] == "whatsapp"
    assert msg.metadata["whatsapp"]["to"] == "whatsapp:+14155238886"


# ── Unit: signature validation ────────────────────────────────────────────


def test_validate_twilio_signature_accepts_and_rejects():
    token = "test-auth-token"
    url = "https://pf.example/webhooks/whatsapp"
    params = {"Body": "hi", "From": "whatsapp:+234", "To": "whatsapp:+1"}
    payload = url + "".join(k + params[k] for k in sorted(params))
    good = base64.b64encode(
        hmac.new(token.encode(), payload.encode("utf-8"), hashlib.sha1).digest()
    ).decode()

    assert validate_twilio_signature(token, url, params, good) is True
    assert validate_twilio_signature(token, url, params, "not-the-signature") is False
    assert validate_twilio_signature(token, url, params, "") is False


# ── Unit: outbound client factory ─────────────────────────────────────────


def test_build_client_null_without_creds():
    s = Settings(WHATSAPP_PROVIDER="twilio", TWILIO_ACCOUNT_SID="", TWILIO_AUTH_TOKEN="")
    assert isinstance(build_whatsapp_client(s), NullWhatsAppClient)


def test_build_client_twilio_with_creds():
    s = Settings(
        WHATSAPP_PROVIDER="twilio",
        TWILIO_ACCOUNT_SID="AC123",
        TWILIO_AUTH_TOKEN="tok",
        TWILIO_WHATSAPP_FROM="whatsapp:+14155238886",
    )
    assert isinstance(build_whatsapp_client(s), TwilioWhatsAppClient)


async def test_null_client_send_is_safe():
    sid = await NullWhatsAppClient().send_text(to="whatsapp:+234", body="hello")
    assert sid == "null-whatsapp"


# ── Pipeline: same brain, WhatsApp envelope ───────────────────────────────


async def test_whatsapp_pipeline_persists_turns(session):
    tenant = Tenant(slug=f"wa-{uuid.uuid4().hex[:8]}", name="WA Test")
    session.add(tenant)
    await session.flush()

    inbound = WhatsAppInbound.from_twilio_form(
        {**_TWILIO_FORM, "Body": "hi there", "WaId": "2340001112222"}
    )
    msg = WhatsAppAdapter.to_inbound(inbound, tenant_slug=tenant.slug)

    chunks = [
        c
        async for c in handle_inbound(
            msg, db=session, redis=None, orchestrator=EchoOrchestrator()
        )
    ]
    assert [c.type for c in chunks] == ["typing", "message", "done"]
    assert chunks[1].content == "You said: hi there"

    conv = (
        await session.execute(
            select(Conversation).where(Conversation.tenant_id == tenant.id)
        )
    ).scalar_one()
    assert conv.channel_type == ChannelType.whatsapp
    assert conv.external_thread_id == "2340001112222"

    rows = (
        await session.execute(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at)
        )
    ).scalars().all()
    assert [r.role for r in rows] == [MessageRole.guest, MessageRole.assistant]
    assert rows[0].content == "hi there"
    assert rows[1].content == "You said: hi there"
