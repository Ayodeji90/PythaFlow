"""WhatsApp webhook endpoints (Day 15).

- `GET  /webhooks/whatsapp` — Meta/360dialog verification challenge
- `POST /webhooks/whatsapp` — inbound messages + status callbacks

Tenant resolution: a guest messages a business number; that number
(`phone_number_id`, falling back to `display_phone_number`) maps to a
`Channel(type=whatsapp)` row → tenant. Seed the channel (see scripts/seed.py).

Outbound: the concierge reply is sent back as a WhatsApp text via the BSP
client — streamed tokens collapse to one message (no token streaming on WA).
Proactive outbound (confirmations/reminders) flows through the notify()
subscriber in `channels/whatsapp/transport.py`, so this router stays
reply-only.

The webhook secret (`WHATSAPP_APP_SECRET`) is the only real auth on this
endpoint. In dev with no secret configured it skips verification loudly —
never ship that to a non-dev environment.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..channels.base import TenantNotFound, handle_inbound
from ..channels.whatsapp.adapter import (
    ParsedWhatsAppMessage,
    WhatsAppAdapter,
    parse_whatsapp_payload,
)
from ..channels.whatsapp.client import WhatsAppSendError
from ..channels.whatsapp.factory import build_whatsapp_client
from ..channels.whatsapp.retry import send_with_retry
from ..config import get_settings, is_dev_env
from ..deps import get_db
from ..models import Channel, Conversation, Message, Tenant
from ..models.enums import ChannelType, MessageRole
from ..services.redis import get_redis_client

log = logging.getLogger("concierge.whatsapp")
router = APIRouter()


# ── Signature verification (X-Hub-Signature-256) ─────────────────────────


def _is_valid_signature(secret: str, raw_body: bytes, signature: str) -> bool:
    """Constant-time compare of `sha256=<hmac-sha256(secret, raw_body)>`."""
    if not secret or not signature:
        return False
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ── Tenant routing by business number ────────────────────────────────────


async def _resolve_tenant_by_number(db: AsyncSession, wa_msg: ParsedWhatsAppMessage) -> Tenant:
    number = wa_msg.phone_number_id or wa_msg.display_phone_number
    if not number:
        raise TenantNotFound("whatsapp payload carries no business number")

    channel = (
        await db.execute(
            select(Channel).where(
                Channel.type == ChannelType.whatsapp,
                Channel.external_id == number,
                Channel.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if channel is None:
        raise TenantNotFound(f"no active whatsapp channel for '{number}'")

    tenant = await db.get(Tenant, channel.tenant_id)
    if tenant is None:
        raise TenantNotFound(f"tenant for whatsapp channel '{number}' not found")
    return tenant


# ── Webhook ──────────────────────────────────────────────────────────────


@router.get("/webhooks/whatsapp")
async def whatsapp_verify(
    hub_mode: str | None = None,
    hub_verify_token: str | None = None,
    hub_challenge: str | None = None,
) -> Response:
    """Meta's verification handshake: echo the challenge when the token matches."""
    settings = get_settings()
    if (
        hub_mode == "subscribe"
        and hub_verify_token
        and hub_verify_token == settings.WHATSAPP_VERIFY_TOKEN
        and hub_challenge
    ):
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="verification failed")


@router.post("/webhooks/whatsapp")
async def whatsapp_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Receive an inbound WhatsApp message and process through the concierge."""
    settings = get_settings()
    raw = await request.body()
    signature = request.headers.get("x-hub-signature-256", "")

    # HMAC is the only auth: with a secret configured, bad signatures are
    # rejected before the body is ever parsed or processed.
    if settings.WHATSAPP_APP_SECRET:
        if not _is_valid_signature(settings.WHATSAPP_APP_SECRET, raw, signature):
            log.warning("whatsapp webhook: bad or missing signature — body dropped")
            raise HTTPException(status_code=401, detail="invalid signature")
    elif not is_dev_env(settings.ENV):
        log.error("whatsapp webhook: no WHATSAPP_APP_SECRET configured outside dev")
        raise HTTPException(status_code=500, detail="webhook secret not configured")

    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid json body") from exc

    messages, statuses = parse_whatsapp_payload(payload)
    for status in statuses:
        await _record_status(db, status)

    if not messages:
        return {"status": "accepted", "detail": "no inbound messages"}

    client = build_whatsapp_client(settings)
    for wa_msg in messages:
        await _process_message(request, db, wa_msg, client)
    return {"status": "accepted", "detail": f"processed {len(messages)} message(s)"}


async def _process_message(
    request: Request,
    db: AsyncSession,
    wa_msg: ParsedWhatsAppMessage,
    client: Any,
) -> None:
    """One inbound message through the shared pipeline, reply sent via BSP."""
    if wa_msg.message_type != "text":
        log.info("ignoring unsupported whatsapp message type=%s", wa_msg.message_type)
        return

    try:
        tenant = await _resolve_tenant_by_number(db, wa_msg)
    except TenantNotFound:
        log.warning(
            "whatsapp: no tenant for business number %s — dropping",
            wa_msg.phone_number_id,
        )
        return

    msg = WhatsAppAdapter.to_inbound(wa_msg, tenant_slug=tenant.slug)
    orchestrator: Any = request.app.state.orchestrator
    parts: list[str] = []
    async for chunk in handle_inbound(
        msg, db=db, redis=get_redis_client(), orchestrator=orchestrator
    ):
        # Day 18: while staff have taken over, the pipeline yields a "paused"
        # notice — keep it out of the WhatsApp outbound (staff reply instead),
        # it still shows in the console transcript.
        if chunk.metadata.get("paused"):
            continue
        if chunk.content and chunk.type in ("token", "message"):
            parts.append(chunk.content)

    reply = "".join(parts)
    if reply:
        # No token streaming on WhatsApp — the assembled reply goes as one text.
        # Day 16: bounded retry + stamp the provider id on the persisted
        # assistant turn so delivery receipts can find it.
        try:
            msg_id = await send_with_retry(
                lambda: client.send_text(to=wa_msg.wa_id, body=reply)
            )
            await _stamp_reply_message(db, tenant, wa_msg.wa_id, msg_id)
            log.info("whatsapp reply sent to %s (provider id %s)", wa_msg.wa_id, msg_id)
        except WhatsAppSendError:
            log.exception("whatsapp reply to %s failed", wa_msg.wa_id)


# ── Delivery receipts (Day 16) ───────────────────────────────────────────


async def _record_status(db: AsyncSession, status: dict) -> None:
    """Persist a delivery/read receipt on the outbound Message it names.

    Meta's webhook reports ``sent | delivered | read | failed`` callbacks keyed
    by the provider message id (``status["id"]`` == the ``wamid``). We stamped
    that id on the outbound Message.meta at send time (reply path and
    transport), so this is a straight lookup + meta update — the console
    (Day 17) renders the ticks from ``meta["delivery"]``.
    """
    wa_msg_id = status.get("id")
    state = status.get("status")
    if not wa_msg_id or not state:
        return
    msg = (
        await db.execute(
            select(Message).where(
                Message.meta["wa_message_id"].astext == str(wa_msg_id)
            )
        )
    ).scalars().first()
    if msg is None:
        log.warning(
            "whatsapp status %s for unknown message %s — not persisted",
            state,
            wa_msg_id,
        )
        return

    delivery = dict(msg.meta.get("delivery") or {})
    delivery[state] = status.get("timestamp") or datetime.now(UTC).isoformat()
    if state == "failed":
        errors = status.get("errors") or []
        if errors:
            delivery["error"] = errors[0].get("message", "unknown")
    msg.meta = {**msg.meta, "delivery": delivery}
    await db.commit()
    log.info("whatsapp status %s recorded on message %s", state, msg.id)


async def _stamp_reply_message(
    db: AsyncSession, tenant: Tenant, thread_id: str, provider_id: str
) -> None:
    """Attach the provider message id to the assistant turn the shared pipeline
    just persisted, so delivery receipts for this reply can find it.

    Known race (sandbox-acceptable, revisit Day 17 when ticks matter): we stamp
    the *latest* assistant message for the thread. Inbound turns are serialised
    by the Day-4 turn lock, so within the pipeline this is correct; but a second
    turn that commits during a slow BSP send could grab the stamp. Cheap enough
    to harden later by threading the assistant Message id out of the pipeline.
    """
    conv = (
        await db.execute(
            select(Conversation).where(
                Conversation.tenant_id == tenant.id,
                Conversation.external_thread_id == thread_id,
            )
        )
    ).scalars().first()
    if conv is None:
        return
    msg = (
        await db.execute(
            select(Message)
            .where(
                Message.conversation_id == conv.id,
                Message.role == MessageRole.assistant,
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if msg is None:
        return
    msg.meta = {**msg.meta, "channel": "whatsapp", "wa_message_id": provider_id}
    await db.commit()
