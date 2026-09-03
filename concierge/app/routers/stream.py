"""Staff console • near-real-time SSE event stream (Day 17 W3-D17-4).

`GET /api/conversations/{id}/events` is a Server-Sent Events stream that pushes
JSON envelopes every time the system publishes a notification for the
conversation (or — when called on the tenant-wide stream — for *any* conversation
in the tenant; see `stream_conversation_events` accepting `tenant_only=True`).

Backed by Redis pub/sub (`app.notifications.channel_key`). If Redis is down,
the connection still serves a periodic heartbeat so the client can detect the
stale state via its own reconnect timer and fall back to polling (`GET .../messages`
on Day 18 will be the polling sibling — for now, the client is expected to
re-open the SSE on error).
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..deps import get_db
from ..deps_console import (
    require_console_token,
    require_tenant_via_token_or_slug,
)
from ..models import Conversation, Tenant
from ..services.redis import get_redis_client

log = logging.getLogger("concierge.sse")
router = APIRouter()


async def _authorise_conv(db: AsyncSession, tenant: Tenant, conv_id: UUID) -> Conversation:
    """Cross-tenant access must look identical to a missing row."""
    conv = await db.get(Conversation, conv_id)
    if conv is None or conv.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="conversation not found")
    return conv


@router.get("/api/conversations/{conversation_id}/events")
async def stream_conversation_events(
    conversation_id: UUID,
    request: Request,
    token: Annotated[str, Depends(require_console_token)],
    tenant: Annotated[Tenant, Depends(require_tenant_via_token_or_slug)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    settings = get_settings()
    conv = await _authorise_conv(db, tenant, conversation_id)

    heartbeat = max(1.0, settings.CONSOLE_SSE_HEARTBEAT_SECONDS)
    max_age = max(10, settings.CONSOLE_SSE_MAX_AGE_SECONDS)

    async def event_iter() -> AsyncIterator[dict]:
        client = get_redis_client()
        try:
            pubsub = client.pubsub()
            await pubsub.subscribe(
                f"concierge:events:{conv.id}",
                "concierge:events:tenant-broadcast",
            )
            log.info("SSE subscribed tenant=%s conv=%s", tenant.slug, conv.id)
        except Exception:  # noqa: BLE001 — Redis down → stream heartbeats only
            log.exception("SSE subscribe failed; streaming heartbeats only")
            pubsub = None

        loop = asyncio.get_event_loop()
        started = loop.time()
        try:
            # Heartbeat immediately so clients always get one event after connect.
            yield {"event": "heartbeat"}
            while True:
                if loop.time() - started > max_age:
                    log.info("SSE max-age reached, closing %s", conv.id)
                    return
                if await request.is_disconnected():
                    log.info("SSE client disconnected %s", conv.id)
                    return

                if pubsub is not None:
                    msg = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=0.5
                    )
                    if msg and msg.get("type") == "message":
                        try:
                            envelope = json.loads(msg["data"])
                        except (TypeError, ValueError):
                            envelope = {"raw": msg["data"]}
                        # Tenant-broadcast only emits if it matches this tenant
                        # (the publisher includes tenant_id); the per-conv
                        # channel is stronger so we trust it as-is.
                        if (
                            envelope.get("conversation_id") is None
                            and envelope.get("tenant_id") != str(tenant.id)
                        ):
                            continue
                        yield {"event": "notification", "data": envelope}
                        continue

                await asyncio.sleep(0.5)
                yield {"event": "heartbeat"}
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe()
                    await pubsub.aclose()
                except Exception:  # noqa: BLE001
                    pass

    from fastapi.responses import StreamingResponse

    async def sse_format() -> AsyncIterator[bytes]:
        async for evt in event_iter():
            ev = evt.get("event", "message")
            data = evt.get("data")
            if data is None:
                yield f"event: {ev}\n\n".encode()
            else:
                yield f"event: {ev}\ndata: {json.dumps(data, default=str)}\n\n".encode()

    return StreamingResponse(
        sse_format(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )
