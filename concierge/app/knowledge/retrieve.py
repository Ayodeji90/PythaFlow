"""Retrieval — the R in RAG.

Embeds the guest's question (query side), runs a tenant-scoped cosine search over
`knowledge_chunks` using the HNSW index, and applies the **similarity floor**:
matches worse than `RAG_MAX_DISTANCE` are dropped. If nothing survives, the
caller injects no context and the concierge says it'll check with the team —
which is how we get "no invention" rather than answering from a bad match.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..llm.embeddings import EmbeddingService, build_embedding_service
from ..models import KnowledgeChunk


@dataclass
class RetrievedChunk:
    title: str | None
    content: str
    source: str | None
    distance: float


async def retrieve(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    query: str,
    k: int | None = None,
    max_distance: float | None = None,
    embedder: EmbeddingService | None = None,
) -> list[RetrievedChunk]:
    s = get_settings()
    k = k or s.RAG_TOP_K
    max_distance = s.RAG_MAX_DISTANCE if max_distance is None else max_distance
    embedder = embedder or build_embedding_service()

    q_vec = await embedder.embed_query(query)

    distance = KnowledgeChunk.embedding.cosine_distance(q_vec).label("distance")
    rows = (
        await db.execute(
            select(
                KnowledgeChunk.title,
                KnowledgeChunk.content,
                KnowledgeChunk.source,
                distance,
            )
            .where(
                KnowledgeChunk.tenant_id == tenant_id,       # tenant isolation
                KnowledgeChunk.embedding.isnot(None),
            )
            .order_by(distance)
            .limit(k)
        )
    ).all()

    return [
        RetrievedChunk(
            title=r.title, content=r.content, source=r.source, distance=float(r.distance)
        )
        for r in rows
        if float(r.distance) <= max_distance   # the similarity floor
    ]


def format_context(chunks: list[RetrievedChunk]) -> str:
    """Render retrieved chunks as tagged context for the system prompt."""
    blocks = []
    for i, c in enumerate(chunks, 1):
        head = f"[{i}]" + (f" {c.title}" if c.title else "")
        blocks.append(f"{head}\n{c.content}")
    return "\n\n".join(blocks)
