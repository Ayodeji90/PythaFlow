"""Notification service abstraction: events + stub handlers.

Other parts of the system call notify() when something happens (Request created,
approved, rejected). Today it logs; tomorrow it sends WhatsApp / email / staff
dashboard push. Adding a channel means adding a subscriber — callers don't change.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

log = logging.getLogger("concierge.notifications")

# Event types — the vocabulary grows as channels are added.
NOTIF_REQUEST_CREATED = "request.created"
NOTIF_REQUEST_APPROVED = "request.approved"
NOTIF_REQUEST_REJECTED = "request.rejected"
NOTIF_MESSAGE_SENT = "message.sent"  # Day 12: confirmation/reminder delivery
NOTIF_ESCALATED = "escalation.created"  # Day 19: a conversation needs a human

# Subscribers per event. A handler is an async callable with the same signature
# as notify() minus the event name:
#     async def handler(event, *, tenant_id, request_id, payload) -> None
# Registered once at startup (see app.main) — e.g. the WhatsApp transport
# (Day 15) subscribes to NOTIF_MESSAGE_SENT to deliver over WhatsApp.
Subscriber = Callable[..., Awaitable[None]]
_SUBSCRIBERS: dict[str, list[Subscriber]] = defaultdict(list)


def register_subscriber(event: str, handler: Subscriber) -> None:
    """Register an async handler to receive `event` notifications.

    idempotent-ish: appending the same bound method twice is harmless because
    the transport is a no-op for anything but its event.
    """
    _SUBSCRIBERS[event].append(handler)


async def notify(
    event: str,
    *,
    tenant_id: UUID | str,
    request_id: UUID | None,
    payload: dict[str, Any],
) -> None:
    """Dispatch an event to all registered handlers (plus the log).

    Callers fire-and-forget this — it never blocks the request path. A failing
    subscriber is logged and isolated so it can never break the caller.
    """
    log.info(
        "notification event=%s tenant=%s request=%s payload=%s",
        event,
        tenant_id,
        request_id,
        payload,
    )
    for handler in list(_SUBSCRIBERS.get(event, ())):
        try:
            await handler(event, tenant_id=tenant_id, request_id=request_id, payload=payload)
        except Exception:  # noqa: BLE001 - a subscriber must never break the caller
            log.exception("notification subscriber for %s failed", event)
