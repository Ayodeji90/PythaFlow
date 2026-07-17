"""Test fixtures. Each test runs inside a transaction that is rolled back at the
end, so tests never pollute the database and never see each other's rows.

Assumes the schema is already migrated (`alembic upgrade head`)."""
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(get_settings().DATABASE_URL, poolclass=NullPool)
    conn = await engine.connect()
    trans = await conn.begin()
    maker = async_sessionmaker(bind=conn, expire_on_commit=False)
    async with maker() as s:
        yield s
    await trans.rollback()
    await conn.close()
    await engine.dispose()
