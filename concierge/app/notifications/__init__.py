"""Notification service abstraction: events + stub handlers.

Other parts of the system call notify() when something happens (Request created,
approved, rejected). Today it logs; tomorrow it sends WhatsApp / email / staff
dashboard push. Adding a channel means adding a subscriber — callers don't change.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

log = logging.getLogger("concierge.notifications")

# Event types — the vocabulary grows as channels are added.
NOTIF_REQUEST_CREATED = "request.created"
NOTIF_REQUEST_APPROVED = "request.approved"
NOTIF_REQUEST_REJECTED = "request.rejected"
NOTIF_MESSAGE_SENT = "message.sent"  # Day 12: confirmation/reminder delivery


async def notify(
    event: str,
    *,
    tenant_id: UUID,
    request_id: UUID,
    payload: dict[str, Any],
) -> None:
    """Dispatch an event to all registered handlers (currently just the logger).

    Callers fire-and-forget this — it never blocks the request path.
    """
    log.info(
        "notification event=%s tenant=%s request=%s payload=%s",
        event,
        tenant_id,
        request_id,
        payload,
    )