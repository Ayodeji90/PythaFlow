"""FastAPI dependencies — request-scoped DB session, shared Redis client, and
the console's shared tenant lookup."""
from collections.abc import AsyncIterator

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import SessionLocal
from .models import Tenant
from .services.redis import get_redis_client


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def get_redis():
    return get_redis_client()


async def resolve_tenant_or_404(db: AsyncSession, slug: str) -> Tenant:
    """Tenant by slug for the staff endpoints — 404 when unknown."""
    tenant = (
        await db.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail=f"unknown tenant '{slug}'")
    return tenant
