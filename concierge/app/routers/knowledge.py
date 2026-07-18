"""Knowledge-base ingestion endpoint. `POST /api/kb` chunks, embeds, and upserts
a document for a tenant."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import get_db
from ..knowledge.ingest import ingest_text
from ..models import Tenant

router = APIRouter()


class KBRequest(BaseModel):
    tenant: str
    source: str
    text: str
    title: str | None = None


class KBResponse(BaseModel):
    source: str
    chunks: int


@router.post("/api/kb", response_model=KBResponse)
async def ingest(req: KBRequest, db: AsyncSession = Depends(get_db)) -> KBResponse:
    tenant = (
        await db.execute(select(Tenant).where(Tenant.slug == req.tenant))
    ).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail=f"unknown tenant '{req.tenant}'")

    result = await ingest_text(
        db, tenant_id=tenant.id, source=req.source, text=req.text, title=req.title
    )
    return KBResponse(source=result.source, chunks=result.chunks)
