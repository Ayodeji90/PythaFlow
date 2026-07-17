"""KnowledgeChunk — a chunk of the venue's knowledge, embedded for RAG (Day 5).
The `embedding` dimension follows Settings.EMBED_DIM (NVIDIA nv-embedqa-e5-v5 =
1024). Changing the embedding provider/dim means a re-embed + a migration."""
from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..config import get_settings
from .base import Base, TenantMixin, TimestampMixin, UUIDMixin

_EMBED_DIM = get_settings().EMBED_DIM


class KnowledgeChunk(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_chunks"

    source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text, default="", server_default="")
    embedding: Mapped[list[float] | None] = mapped_column(Vector(_EMBED_DIM), nullable=True)
    meta: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
