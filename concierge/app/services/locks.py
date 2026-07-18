"""Per-conversation turn lock.

Without this, a guest who sends two messages quickly gets two LLM replies
generated concurrently against the same history — they interleave, and the second
reply never sees the first. The lock **serialises** turns (waits its turn) rather
than rejecting them, so a fast follow-up is answered, not dropped.

A no-op when `redis` is None, so tests and offline paths don't need Redis.
"""
from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

# Safety valve: if a turn dies mid-flight, the key expires rather than wedging
# the conversation forever.
LOCK_TTL_SECONDS = 60
# How long a queued turn waits for the one ahead of it before giving up.
LOCK_WAIT_SECONDS = 30.0
_POLL_INTERVAL = 0.05


@asynccontextmanager
async def conversation_turn_lock(
    redis: Any,
    conversation_id: uuid.UUID,
    *,
    ttl: int = LOCK_TTL_SECONDS,
    wait: float = LOCK_WAIT_SECONDS,
) -> AsyncIterator[bool]:
    """Yields True if we hold the lock, False if we gave up waiting."""
    if redis is None:
        yield True
        return

    key = f"conv:{conversation_id}:turn"
    acquired = False
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait

    while True:
        acquired = bool(await redis.set(key, "1", nx=True, ex=ttl))
        if acquired or loop.time() >= deadline:
            break
        await asyncio.sleep(_POLL_INTERVAL)

    try:
        yield acquired
    finally:
        if acquired:
            try:
                await redis.delete(key)
            except Exception:  # noqa: BLE001 - never fail a turn on cleanup
                pass
