"""Ingestion: chunk → embed → store, scoped to a tenant.

Upsert semantics: re-ingesting the same `source` for a tenant replaces that
source's chunks (delete-then-insert) so editing a venue's hours doesn't leave
stale copies behind.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..llm.embeddings import EmbeddingService, build_embedding_service
from ..models import KnowledgeChunk
from .chunk import chunk_document


@dataclass
class IngestResult:
    source: str
    chunks: int


async def ingest_text(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    source: str,
    text: str,
    title: str | None = None,
    embedder: EmbeddingService | None = None,
) -> IngestResult:
    embedder = embedder or build_embedding_service()

    chunks = chunk_document(text, base_title=title)
    if not chunks:
        return IngestResult(source=source, chunks=0)

    # Embed as passages (document side of the asymmetric retrieval model).
    vectors = await embedder.embed_documents([c.content for c in chunks])

    # Replace any prior version of this source for this tenant.
    await db.execute(
        delete(KnowledgeChunk).where(
            KnowledgeChunk.tenant_id == tenant_id,
            KnowledgeChunk.source == source,
        )
    )
    for c, vec in zip(chunks, vectors, strict=True):
        db.add(
            KnowledgeChunk(
                tenant_id=tenant_id,
                source=source,
                title=c.title,
                content=c.content,
                embedding=vec,
                meta={"chars": len(c.content)},
            )
        )
    await db.commit()
    return IngestResult(source=source, chunks=len(chunks))
