"""Bounded retry with backoff for WhatsApp outbound sends (Day 16).

A transient BSP failure (timeout, network blip, 5xx) is retried a bounded
number of times with exponential backoff; a permanent rejection surfaces
immediately. Callers keep the provider message id returned by the *first*
success and persist it (see transport.py idempotency), so a retry can never
double-send.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from .client import WhatsAppSendError

log = logging.getLogger("concierge.whatsapp.retry")

DEFAULT_ATTEMPTS = 3
DEFAULT_BASE_DELAY = 0.2  # seconds; doubles each attempt (0.2 → 0.4 → 0.8 …)


async def send_with_retry(
    send: Callable[[], Awaitable[str]],
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY,
) -> str:
    """Call ``send()`` up to ``attempts`` times with exponential backoff.

    Returns the provider message id of the first successful send. Raises the
    last exception once attempts are exhausted. ``WhatsAppSendError`` and
    ``OSError`` (network) are retried; anything else propagates immediately so
    a programming error is never masked by retries.
    """
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await send()
        except (WhatsAppSendError, OSError) as exc:
            last = exc
            if attempt < attempts:
                delay = base_delay * (2 ** (attempt - 1))
                log.warning(
                    "whatsapp send attempt %d/%d failed (%s) — retrying in %.1fs",
                    attempt,
                    attempts,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
    assert last is not None  # attempts >= 1 by construction
    raise last
