"""Async SQLAlchemy engine + session factory. The declarative `Base` is the
root for the models added on Day 2."""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models (populated Day 2)."""


_settings = get_settings()

engine = create_async_engine(_settings.DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def ping_db() -> bool:
    """True if a trivial query round-trips. Used by /health and lifespan."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
