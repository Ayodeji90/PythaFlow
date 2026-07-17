"""Shared async Redis client (session/hot state from Day 4 onward)."""
import asyncio
from functools import lru_cache

import redis.asyncio as redis

from ..config import get_settings


@lru_cache
def get_redis_client() -> "redis.Redis":
    s = get_settings()
    return redis.from_url(
        s.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        # Bound connect + command sockets so a stalled Redis degrades promptly.
        socket_connect_timeout=s.REDIS_CONNECT_TIMEOUT,
        socket_timeout=s.REDIS_SOCKET_TIMEOUT,
    )


async def ping_redis() -> bool:
    try:
        return bool(
            await asyncio.wait_for(
                get_redis_client().ping(),
                timeout=get_settings().HEALTH_PROBE_TIMEOUT,
            )
        )
    except Exception:
        return False
