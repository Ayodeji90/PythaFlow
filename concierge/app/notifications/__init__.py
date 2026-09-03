"""Notification service abstraction: events + subscribers.

Other parts of the system call notify() when something happens (Request created,
approved, rejected, message sent). Subscribers do whatever they want — today
a logger + a Redis pub/sub publisher (the SSE bridge for the staff console,
Day 17). Adding a channel means adding a subscriber; callers don't change.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from ..services.redis import get_redis_client

log = logging.getLogger("concierge.notifications")

# Event types — the vocabulary grows as channels are added.
NOTIF_REQUEST_CREATED = "request.created"
NOTIF_REQUEST_APPROVED = "request.approved"
NOTIF_REQUEST_REJECTED = "request.rejected"
NOTIF_MESSAGE_SENT = "message.sent"  # Day 12: confirmation/reminder delivery

REDIS_CHANNEL_PREFIX = "concierge:events:"


def channel_key(conversation_id: UUID | None) -> str:
    """Redis pub/sub key; ``*`` broadcasts to the console tenant-wide."""
    if conversation_id is None:
        return f"{REDIS_CHANNEL_PREFIX}tenant-broadcast"
    return f"{REDIS_CHANNEL_PREFIX}{conversation_id}"


async def notify(
    event: str,
    *,
    tenant_id: UUID,
    request_id: UUID,
    payload: dict[str, Any],
    conversation_id: UUID | None = None,
) -> None:
    """Dispatch an event: log it, publish it (best-effort).

    Callers fire-and-forget — publish failure never raises, so a Redis outage
    can never break a request path.
    """
    log.info(
        "notification event=%s tenant=%s request=%s payload=%s",
        event,
        tenant_id,
        request_id,
        payload,
    )
    envelope = {
        "event": event,
        "tenant_id": str(tenant_id),
        "request_id": str(request_id),
        "conversation_id": str(conversation_id) if conversation_id else None,
        "at": datetime.now(UTC).isoformat(),
        "payload": payload,
    }
    try:
        client = get_redis_client()
        msg = json.dumps(envelope, default=str)
        await client.publish(channel_key(conversation_id), msg)
        # Always also publish on the tenant-broadcast channel so SSE listeners
        # subscribed to "all of my tenant's events" don't miss conv-specific ones.
        if conversation_id is not None:
            await client.publish(channel_key(None), msg)
    except Exception:  # noqa: BLE001 — notifications are best-effort
        log.exception("failed to publish notification event=%s", event)
