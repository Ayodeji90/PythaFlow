"""Near-real-time console updates (Day 17) via Server-Sent Events.

`GET /api/stream?tenant=<slug>&token=...` — the console opens one EventSource
and receives tiny ``conversations_changed`` events carrying the ids of
conversations that gained a message or changed status since the last tick;
the client refetches ``/api/conversations`` and patches its list.

Design note: this polls the DB every POLL_INTERVAL (2s) rather than pushing
through Redis pub/sub. Rationale: the repo treats Redis as optional everywhere
(graceful fallbacks), the change signal lives in Postgres rows (messages), and
fan-out via the ``notify()`` seam arrives with Day 19's real notification
subscribers — swapping the poll for a Redis subscription then is a ~15-line
change behind this same endpoint. The console also re-polls every 5s on its
side as a fallback if the stream drops.

Auth: EventSource cannot set headers, so the token rides the query string
(``?token=``) — a stopgap loudly documented; real auth is Day 24.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select, union

from ..db import SessionLocal
from ..deps import resolve_tenant_or_404
from ..models import Conversation, Message
from .console_auth import require_staff_token_param

log = logging.getLogger("concierge.routers.stream")
router = APIRouter()

POLL_INTERVAL_SECONDS = 2.0


async def _changed_conversation_ids(tenant_id, since: datetime) -> list[str]:
    """Conversations with a new message or a status change since `since`."""
    new_messages = select(Message.conversation_id).where(
        Message.tenant_id == tenant_id, Message.created_at > since
    )
    status_changes = select(Conversation.id).where(
        Conversation.tenant_id == tenant_id, Conversation.updated_at > since
    )
    merged = union(new_messages, status_changes).alias("changed")
    async with SessionLocal() as db:
        # Compound-select columns take their name from the first select
        # (conversation_id), not a positional column_0.
        rows = (await db.execute(select(merged.c.conversation_id))).scalars().all()
    return [str(r) for r in rows]


@router.get("/api/stream", include_in_schema=False)
async def stream_events(
    tenant: str,
    _: str = Depends(require_staff_token_param),
) -> StreamingResponse:
    """SSE: emits ``conversations_changed`` events (ids) every tick."""
    async with SessionLocal() as db:
        t = await resolve_tenant_or_404(db, tenant)
        tenant_id = t.id
    # Mutable cell so the nested generator can advance the cursor without
    # rebinding the outer name (which would make it an unbound local).
    cursor = [datetime.now(UTC)]

    async def _events() -> Any:
        try:
            yield "event: connected\ndata: {}\n\n"
            while True:
                # Capture the tick boundary *before* querying so a change that
                # lands mid-tick is caught by the next poll, never skipped.
                tick = datetime.now(UTC)
                changed = await _changed_conversation_ids(tenant_id, cursor[0])
                cursor[0] = tick
                if changed:
                    payload = {"ids": changed}
                    yield f"event: conversations_changed\ndata: {json.dumps(payload)}\n\n"
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            log.info("console stream for tenant %s closed (client gone)", tenant)
        except Exception:  # noqa: BLE001 — a dead stream must not kill the app
            log.exception("console stream failed for tenant %s", tenant)

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
