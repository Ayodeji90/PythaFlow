"""Inbound WhatsApp webhook (Twilio).

Twilio POSTs an inbound WhatsApp message here as form-encoded fields. We verify
the signature, map it to the canonical InboundMessage, run the SAME concierge
pipeline as web chat and email, and send the reply back over WhatsApp via the
Twilio REST client. Adding WhatsApp touched no orchestrator or tool code — only
this router + the adapter/client under `channels/whatsapp/`.

Note on latency: this processes synchronously and then replies. On the free-tier
LLM a turn can approach Twilio's webhook timeout; with a fast model (Groq / Azure
Foundry) it's well within budget. Production hardening = process in the background
and reply 200 immediately (tracked for Day 16).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..channels.base import TenantNotFound, handle_inbound
from ..channels.whatsapp import (
    WhatsAppAdapter,
    WhatsAppInbound,
    build_whatsapp_client,
    send_with_retry,
    validate_twilio_signature,
)
from ..config import get_settings
from ..deps import get_db
from ..models import Channel, Conversation, Message, Tenant
from ..models.enums import ChannelType, MessageRole
from ..services.redis import get_redis_client

log = logging.getLogger("concierge.whatsapp")
router = APIRouter()

_EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


async def _resolve_tenant_by_whatsapp(
    db: AsyncSession, to_number: str, default_slug: str
) -> Tenant | None:
    """Route an inbound message to a tenant.

    Primary: match a whatsapp Channel whose `external_id` == the "To" number.
    Fallback: the configured WHATSAPP_DEFAULT_TENANT (handy for the shared Twilio
    sandbox number, where every venue would otherwise share one "To").
    """
    channel = (
        await db.execute(
            select(Channel).where(
                Channel.type == ChannelType.whatsapp,
                Channel.external_id == to_number,
                Channel.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if channel is not None:
        return await db.get(Tenant, channel.tenant_id)

    if default_slug:
        return (
            await db.execute(select(Tenant).where(Tenant.slug == default_slug))
        ).scalar_one_or_none()
    return None


@router.get("/webhooks/whatsapp")
async def whatsapp_health() -> dict[str, str]:
    """Twilio doesn't require a GET verification handshake (that's Meta), but a
    200 here makes the webhook URL easy to sanity-check in a browser."""
    return {"status": "ok", "channel": "whatsapp"}


@router.post("/webhooks/whatsapp")
async def inbound_whatsapp(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    settings = get_settings()
    form = {k: str(v) for k, v in (await request.form()).items()}

    # 1) Prove it's really Twilio (unless disabled / no token configured).
    if settings.WHATSAPP_VALIDATE_SIGNATURE and settings.TWILIO_AUTH_TOKEN:
        signature = request.headers.get("X-Twilio-Signature", "")
        if not validate_twilio_signature(
            settings.TWILIO_AUTH_TOKEN, str(request.url), form, signature
        ):
            raise HTTPException(status_code=403, detail="invalid Twilio signature")

    inbound = WhatsAppInbound.from_twilio_form(form)

    # Status callbacks / media-only messages carry no body — accept and ignore.
    if not inbound.body.strip():
        return Response(content=_EMPTY_TWIML, media_type="text/xml")

    # Day 16: dedupe Twilio inbound retries so a message is never processed twice.
    redis = get_redis_client()
    if inbound.message_sid:
        try:
            fresh = await redis.set(
                f"wa:seen:{inbound.message_sid}", "1", nx=True, ex=3600
            )
            if not fresh:
                log.info(
                    "duplicate WhatsApp delivery %s — skipping", inbound.message_sid
                )
                return Response(content=_EMPTY_TWIML, media_type="text/xml")
        except Exception:  # noqa: BLE001 — dedup is best-effort; proceed if redis is down
            log.warning("WhatsApp dedup check failed — processing anyway")

    tenant = await _resolve_tenant_by_whatsapp(
        db, inbound.to_number, settings.WHATSAPP_DEFAULT_TENANT
    )
    if tenant is None:
        log.warning("no tenant for WhatsApp 'To' %s — discarding", inbound.to_number)
        return Response(content=_EMPTY_TWIML, media_type="text/xml")

    msg = WhatsAppAdapter.to_inbound(inbound, tenant_slug=tenant.slug)
    orchestrator: Any = request.app.state.orchestrator
    redis = get_redis_client()

    parts: list[str] = []
    try:
        async for chunk in handle_inbound(
            msg, db=db, redis=redis, orchestrator=orchestrator
        ):
            if chunk.content and chunk.type in ("token", "message"):
                parts.append(chunk.content)
    except TenantNotFound as e:
        log.warning("tenant not found during WhatsApp processing: %s", e)
        return Response(content=_EMPTY_TWIML, media_type="text/xml")

    reply = "".join(parts)
    if reply:
        client = build_whatsapp_client(settings)
        try:
            sid = await send_with_retry(
                lambda: client.send_text(to=inbound.from_number, body=reply),
                max_retries=settings.WHATSAPP_SEND_MAX_RETRIES,
            )
            log.info("WhatsApp reply sent to %s (sid=%s)", inbound.from_number, sid)
            # Record the sid so delivery/read receipts can update this message.
            await _record_outbound_sid(db, tenant.id, inbound.wa_id, sid)
        except Exception:  # noqa: BLE001 — outbound failure shouldn't 500 the webhook
            log.exception("failed to send WhatsApp reply to %s", inbound.from_number)

    return Response(content=_EMPTY_TWIML, media_type="text/xml")


async def _record_outbound_sid(
    db: AsyncSession, tenant_id, thread_ref: str, sid: str
) -> None:
    """Stamp the provider message id onto the assistant turn we just sent, so a
    later status callback can update its delivery state."""
    conv = (
        await db.execute(
            select(Conversation).where(
                Conversation.tenant_id == tenant_id,
                Conversation.external_thread_id == thread_ref,
            )
        )
    ).scalar_one_or_none()
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
    msg.meta = {**(msg.meta or {}), "whatsapp_sid": sid, "whatsapp_status": "sent"}
    await db.commit()


async def _apply_status(db: AsyncSession, sid: str, status: str) -> None:
    """Update the delivery status recorded on the outbound message with this sid."""
    msg = (
        await db.execute(
            select(Message).where(Message.meta["whatsapp_sid"].astext == sid)
        )
    ).scalars().first()
    if msg is None:
        log.info("WhatsApp status '%s' for unknown sid %s", status, sid)
        return
    msg.meta = {**(msg.meta or {}), "whatsapp_status": status}
    await db.commit()


@router.post("/webhooks/whatsapp/status")
async def whatsapp_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Twilio delivery/read receipts (sent → delivered → read, or failed)."""
    settings = get_settings()
    form = {k: str(v) for k, v in (await request.form()).items()}
    if settings.WHATSAPP_VALIDATE_SIGNATURE and settings.TWILIO_AUTH_TOKEN:
        signature = request.headers.get("X-Twilio-Signature", "")
        if not validate_twilio_signature(
            settings.TWILIO_AUTH_TOKEN, str(request.url), form, signature
        ):
            raise HTTPException(status_code=403, detail="invalid Twilio signature")

    sid = form.get("MessageSid") or form.get("SmsSid", "")
    status = form.get("MessageStatus") or form.get("SmsStatus", "")
    if sid and status:
        await _apply_status(db, sid, status)
    return Response(content=_EMPTY_TWIML, media_type="text/xml")
