"""Async SQLAlchemy engine + session factory. The declarative `Base` is the
root for the models added on Day 2."""
import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings
from .models.base import Base  # noqa: F401  re-exported for convenience

_settings = get_settings()

engine = create_async_engine(
    _settings.DATABASE_URL,
    pool_pre_ping=True,
    future=True,
    # Bound connection establishment so a network stall can't hang forever
    # (asyncpg's connect `timeout`, in seconds).
    connect_args={"timeout": _settings.DB_CONNECT_TIMEOUT},
)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def ping_db() -> bool:
    """True if a trivial query round-trips within the probe deadline. Used by
    /health and lifespan — bounded so a stalled DB degrades promptly."""
    async def _probe() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(_probe(), timeout=_settings.HEALTH_PROBE_TIMEOUT)
        return True
    except Exception:
        return False
