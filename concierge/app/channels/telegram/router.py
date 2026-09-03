"""Telegram MTProto webhook handler.

Receives Bot API webhook updates (for webhook mode), validates the secret token,
converts to InboundMessage, runs the shared concierge pipeline, and sends replies
via the MTProto client.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...channels.base import handle_inbound
from ...config import get_settings
from ...deps import get_db
from ...models import Channel, Tenant
from ...models.enums import ChannelType
from ...services.redis import get_redis_client
from .adapter import TelegramAdapter, TelegramInbound
from .client import build_telegram_client, send_with_retry

log = logging.getLogger("concierge.telegram")
router = APIRouter()

_EMPTY_RESPONSE = "ok"


async def _resolve_tenant_by_telegram(
    db: AsyncSession, chat_id: int
) -> Tenant | None:
    """Route an inbound Telegram message to a tenant.

    Strategy: Channel.external_id stores the bot username for per-tenant bots.
    For webhook mode, we can't easily determine which bot received the message
    without the bot token in the URL path. For MVP with single bot per tenant,
    we'll look up by the bot username in the Channel row.

    Since we're using per-tenant bots, we need to identify which tenant's bot
    received the message. The webhook URL should be per-tenant:
    /webhooks/telegram/{tenant_slug}
    """
    # For now, try to find any active Telegram channel
    # In production with per-tenant webhooks, the tenant would be in the path
    channel = (
        await db.execute(
            Channel.__table__.select().where(
                Channel.type == ChannelType.telegram,
                Channel.active.is_(True),
            )
        )
    ).first()

    if channel:
        return await db.get(Tenant, channel.tenant_id)

    # Fallback: check for a default tenant setting
    settings = get_settings()
    if settings.TELEGRAM_DEFAULT_TENANT:
        stmt = Tenant.__table__.select().where(
            Tenant.slug == settings.TELEGRAM_DEFAULT_TENANT
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    return None


@router.get("/webhooks/telegram")
async def telegram_health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok", "channel": "telegram"}


@router.post("/webhooks/telegram")
async def inbound_telegram(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Handle inbound Telegram webhook (Bot API format)."""
    settings = get_settings()

    # Validate secret token if configured
    if settings.TELEGRAM_WEBHOOK_SECRET:
        secret_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if secret_token != settings.TELEGRAM_WEBHOOK_SECRET:
            log.warning("Invalid Telegram webhook secret token")
            raise HTTPException(status_code=403, detail="invalid secret token")

    # Parse update
    update = await request.json()

    # Convert to TelegramInbound
    inbound = TelegramInbound.from_webhook_update(update)
    if not inbound:
        # Not a text message in private chat - acknowledge but don't process
        return Response(content=_EMPTY_RESPONSE)

    # Deduplication using update_id
    redis = get_redis_client()
    update_id = update.get("update_id")
    if update_id:
        try:
            fresh = await redis.set(
                f"tg:seen:{update_id}", "1", nx=True, ex=3600
            )
            if not fresh:
                log.info("Duplicate Telegram update %s — skipping", update_id)
                return Response(content=_EMPTY_RESPONSE)
        except Exception:  # noqa: BLE001
            log.warning("Telegram dedup check failed — processing anyway")

    # Resolve tenant
    tenant = await _resolve_tenant_by_telegram(db, inbound.chat_id)
    if tenant is None:
        log.warning("No tenant for Telegram chat_id %s — discarding", inbound.chat_id)
        return Response(content=_EMPTY_RESPONSE)

    # Convert to InboundMessage
    msg = TelegramAdapter.to_inbound(inbound, tenant_slug=tenant.slug)

    # Run the shared pipeline
    orchestrator: Any = request.app.state.orchestrator
    redis = get_redis_client()

    parts: list[str] = []
    try:
        async for chunk in handle_inbound(
            msg, db=db, redis=redis, orchestrator=orchestrator
        ):
            if chunk.content and chunk.type in ("token", "message"):
                parts.append(chunk.content)
    except Exception as e:  # noqa: BLE001
        log.exception("Error processing Telegram message: %s", e)
        return Response(content=_EMPTY_RESPONSE)

    reply = "".join(parts)
    if reply:
        client = build_telegram_client()
        try:
            await send_with_retry(
                lambda: client.send_text(chat_id=inbound.chat_id, text=reply),
                max_retries=3,
            )
            log.info("Telegram reply sent to chat_id %s", inbound.chat_id)
        except Exception:  # noqa: BLE001
            log.exception("Failed to send Telegram reply to %s", inbound.chat_id)

    return Response(content=_EMPTY_RESPONSE)


@router.post("/webhooks/telegram/set")
async def set_telegram_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Helper endpoint to set the Telegram webhook for a tenant's bot.

    Expected body: {"tenant_slug": "venue1", "url": "https://domain.com/webhooks/telegram"}
    """
    from ..models import Channel

    body = await request.json()
    tenant_slug = body.get("tenant_slug")
    webhook_url = body.get("url")

    if not tenant_slug or not webhook_url:
        raise HTTPException(400, "tenant_slug and url required")

    tenant = (
        await db.execute(Tenant.__table__.select().where(Tenant.slug == tenant_slug))
    ).scalar_one_or_none()

    if not tenant:
        raise HTTPException(404, "tenant not found")

    # Get the bot token for this tenant (stored in Channel.config)
    channel = (
        await db.execute(
            Channel.__table__.select().where(
                Channel.tenant_id == tenant.id,
                Channel.type == ChannelType.telegram,
                Channel.active.is_(True),
            )
        )
    ).scalar_one_or_none()

    if not channel or not channel.config:
        raise HTTPException(400, "Telegram channel not configured for tenant")

    bot_token = channel.config.get("bot_token")
    if not bot_token:
        raise HTTPException(400, "Bot token not configured")

    # Call Telegram API to set webhook
    import httpx

    settings = get_settings()
    secret = settings.TELEGRAM_WEBHOOK_SECRET

    async with httpx.AsyncClient(timeout=15.0) as client:
        url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
        data = {
            "url": webhook_url,
            "secret_token": secret,
            "allowed_updates": ["message", "edited_message"],
        }
        resp = await client.post(url, json=data)
        resp.raise_for_status()
        return resp.json()


@router.post("/webhooks/telegram/delete")
async def delete_telegram_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Helper to delete webhook (switch to long polling)."""
    from ..models import Channel

    body = await request.json()
    tenant_slug = body.get("tenant_slug")

    if not tenant_slug:
        raise HTTPException(400, "tenant_slug required")

    tenant = (
        await db.execute(Tenant.__table__.select().where(Tenant.slug == tenant_slug))
    ).scalar_one_or_none()

    if not tenant:
        raise HTTPException(404, "tenant not found")

    channel = (
        await db.execute(
            Channel.__table__.select().where(
                Channel.tenant_id == tenant.id,
                Channel.type == ChannelType.telegram,
                Channel.active.is_(True),
            )
        )
    ).scalar_one_or_none()

    if not channel or not channel.config:
        raise HTTPException(400, "Telegram channel not configured")

    bot_token = channel.config.get("bot_token")
    if not bot_token:
        raise HTTPException(400, "Bot token not configured")

    import httpx

    async with httpx.AsyncClient(timeout=15.0) as client:
        url = f"https://api.telegram.org/bot{bot_token}/deleteWebhook"
        resp = await client.post(url)
        resp.raise_for_status()
        return resp.json()