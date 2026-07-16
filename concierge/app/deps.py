"""FastAPI dependencies — request-scoped DB session and the shared Redis client."""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from .db import SessionLocal
from .services.redis import get_redis_client


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def get_redis():
    return get_redis_client()
