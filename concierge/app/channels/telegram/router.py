"""Telegram Bot API webhook handler.

Each venue has its own bot (token stored in Channel.config["bot_token"]) and
registers it at /webhooks/telegram/{tenant_slug} via setWebhook — the URL path
identifies the tenant, exactly like WhatsApp matches the inbound "To" number.
The shared /webhooks/telegram path is a sandbox convenience that routes to the
configured default tenant.

Flow: validate secret → parse update → Redis dedup (update_id) → resolve tenant
from the path → run the shared concierge pipeline → reply via the SAME bot
token the guest messaged (one identity end to end).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
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


# ── helpers ──────────────────────────────────────────────────────────────────


async def _tenant_by_slug(db: AsyncSession, tenant_slug: str) -> Tenant | None:
    """Look up a tenant by slug (from the webhook path or default setting)."""
    return (await db.execute(select(Tenant).where(Tenant.slug == tenant_slug))).scalar_one_or_none()


async def _telegram_channel(db: AsyncSession, tenant: Tenant) -> Channel | None:
    """The tenant's active Telegram Channel row."""
    return (
        await db.execute(
            select(Channel).where(
                Channel.tenant_id == tenant.id,
                Channel.type == ChannelType.telegram,
                Channel.active.is_(True),
            )
        )
    ).scalar_one_or_none()


def _channel_config(channel: Channel | None) -> dict[str, Any]:
    """Defensive read of Channel.config (JSONB, may be None or empty)."""
    return dict(channel.config or {}) if channel is not None else {}


def _check_secret(request: Request, cfg: dict[str, Any], *, tenant_slug: str) -> None:
    """Verify X-Telegram-Bot-Api-Secret-Token against the venue's secret.

    Per-venue secrets live in Channel.config["webhook_secret"]; the global
    TELEGRAM_WEBHOOK_SECRET env var is the fallback. If no secret is configured
    anywhere the deployment is in dev mode — accept but warn loudly.
    """
    settings = get_settings()
    expected = cfg.get("webhook_secret") or settings.TELEGRAM_WEBHOOK_SECRET
    if not expected:
        log.warning(
            "No Telegram webhook secret configured — accepting unauthenticated "
            "updates (dev mode) for tenant %s",
            tenant_slug,
        )
        return
    actual = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if actual != expected:
        log.warning("Invalid Telegram webhook secret for tenant %s", tenant_slug)
        raise HTTPException(status_code=403, detail="invalid secret token")


async def _handle_telegram_update(
    request: Request,
    db: AsyncSession,
    *,
    tenant_slug: str | None,
) -> Response:
    """Shared inbound handler for the per-tenant and default-tenant paths."""
    update = await request.json()

    # Only text messages in private chats are processed — anything else is
    # acknowledged but ignored (groups/channels are out of scope for MVP).
    inbound = TelegramInbound.from_webhook_update(update)
    if not inbound:
        return Response(content=_EMPTY_RESPONSE)

    # Dedupe Telegram retries by update_id (same pattern as WhatsApp's wa:seen).
    redis = get_redis_client()
    update_id = update.get("update_id")
    if update_id:
        try:
            fresh = await redis.set(f"tg:seen:{update_id}", "1", nx=True, ex=3600)
            if not fresh:
                log.info("Duplicate Telegram update %s — skipping", update_id)
                return Response(content=_EMPTY_RESPONSE)
        except Exception:  # noqa: BLE001 — dedup is best-effort; proceed if redis is down
            log.warning("Telegram dedup check failed — processing anyway")

    # Resolve the tenant from the path (or the default-tenant sandbox setting).
    tenant = await _tenant_by_slug(db, tenant_slug) if tenant_slug else None
    if tenant is None:
        log.warning(
            "No tenant for Telegram update %s (path slug=%r) — discarding",
            update_id,
            tenant_slug,
        )
        return Response(content=_EMPTY_RESPONSE)

    channel = await _telegram_channel(db, tenant)
    cfg = _channel_config(channel)
    _check_secret(request, cfg, tenant_slug=tenant.slug)

    msg = TelegramAdapter.to_inbound(inbound, tenant_slug=tenant.slug)
    orchestrator: Any = request.app.state.orchestrator

    parts: list[str] = []
    try:
        async for chunk in handle_inbound(msg, db=db, redis=redis, orchestrator=orchestrator):
            if chunk.content and chunk.type in ("token", "message"):
                parts.append(chunk.content)
    except Exception as e:  # noqa: BLE001
        log.exception("Error processing Telegram message: %s", e)
        return Response(content=_EMPTY_RESPONSE)

    reply = "".join(parts)
    if reply:
        # The venue's own bot token — the reply comes from the bot the guest
        # messaged, never from a different identity.
        client = build_telegram_client(cfg.get("bot_token"))
        try:
            await send_with_retry(
                lambda: client.send_text(chat_id=inbound.chat_id, text=reply),
                max_retries=3,
            )
            log.info("Telegram reply sent to chat_id %s", inbound.chat_id)
        except Exception:  # noqa: BLE001 — outbound failure shouldn't 500 the webhook
            log.exception("Failed to send Telegram reply to %s", inbound.chat_id)

    return Response(content=_EMPTY_RESPONSE)


# ── routes ───────────────────────────────────────────────────────────────────


@router.get("/webhooks/telegram")
async def telegram_health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok", "channel": "telegram"}


@router.post("/webhooks/telegram")
async def inbound_telegram_default(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Sandbox/single-bot path — routes to TELEGRAM_DEFAULT_TENANT.

    Production multi-tenant deployments use /webhooks/telegram/{tenant_slug}
    (one webhook URL per bot) so the tenant is unambiguous.
    """
    settings = get_settings()
    return await _handle_telegram_update(
        request, db, tenant_slug=settings.TELEGRAM_DEFAULT_TENANT or None
    )


@router.post("/webhooks/telegram/set")
async def set_telegram_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Register a venue's bot webhook at /webhooks/telegram/{tenant_slug}.

    Expected body: {"tenant_slug": "venue1", "url": "https://domain.com"}.
    The per-tenant webhook path is appended to `url` automatically. Stores the
    bot's @username on Channel.external_id for ops visibility.
    """
    body = await request.json()
    tenant_slug = body.get("tenant_slug")
    base_url = body.get("url")

    if not tenant_slug or not base_url:
        raise HTTPException(400, "tenant_slug and url required")

    tenant = await _tenant_by_slug(db, tenant_slug)
    if tenant is None:
        raise HTTPException(404, "tenant not found")

    channel = await _telegram_channel(db, tenant)
    if channel is None:
        raise HTTPException(400, "Telegram channel not configured for tenant")
    cfg = _channel_config(channel)
    bot_token = cfg.get("bot_token")
    if not bot_token:
        raise HTTPException(400, "Bot token not configured")

    settings = get_settings()
    secret = cfg.get("webhook_secret") or settings.TELEGRAM_WEBHOOK_SECRET or None
    webhook_url = f"{base_url.rstrip('/')}/webhooks/telegram/{tenant_slug}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{bot_token}/setWebhook",
            json={
                "url": webhook_url,
                "secret_token": secret,
                "allowed_updates": ["message", "edited_message"],
            },
        )
        resp.raise_for_status()
        # Persist the bot's username so the Channel row identifies the bot.
        me = await client.get(f"https://api.telegram.org/bot{bot_token}/getMe")
        if me.status_code == 200 and me.json().get("ok"):
            username = me.json().get("result", {}).get("username")
            if username:
                channel.external_id = username
                await db.commit()

    return {"ok": True, "webhook_url": webhook_url, "result": resp.json()}


@router.post("/webhooks/telegram/delete")
async def delete_telegram_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Unregister a venue's bot webhook.

    Expected body: {"tenant_slug": "venue1"}.
    """
    body = await request.json()
    tenant_slug = body.get("tenant_slug")

    if not tenant_slug:
        raise HTTPException(400, "tenant_slug required")

    tenant = await _tenant_by_slug(db, tenant_slug)
    if tenant is None:
        raise HTTPException(404, "tenant not found")

    channel = await _telegram_channel(db, tenant)
    if channel is None:
        raise HTTPException(400, "Telegram channel not configured for tenant")
    cfg = _channel_config(channel)
    bot_token = cfg.get("bot_token")
    if not bot_token:
        raise HTTPException(400, "Bot token not configured")

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(f"https://api.telegram.org/bot{bot_token}/deleteWebhook")
        resp.raise_for_status()
        return resp.json()


@router.post("/webhooks/telegram/{tenant_slug}")
async def inbound_telegram_for_tenant(
    tenant_slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Per-tenant webhook path — each venue's bot is registered here.

    Registered after the literal /set and /delete paths so those are matched
    first (FastAPI matches in registration order).
    """
    return await _handle_telegram_update(request, db, tenant_slug=tenant_slug)
