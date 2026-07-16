"""Shared async Redis client (session/hot state from Day 4 onward)."""
from functools import lru_cache

import redis.asyncio as redis

from ..config import get_settings


@lru_cache
def get_redis_client() -> "redis.Redis":
    return redis.from_url(
        get_settings().REDIS_URL, encoding="utf-8", decode_responses=True
    )


async def ping_redis() -> bool:
    try:
        return bool(await get_redis_client().ping())
    except Exception:
        return False
