"""Fixture loader for eval harness — seeds tenants and KB data.

Each fixture creates a tenant and ingests the venue's knowledge base markdown
into ``KnowledgeChunk`` rows (without real embeddings — the eval uses replay mode
and doesn't need vector search).
"""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Lazy imports inside functions to avoid loading the full app at module level
log = logging.getLogger("evals.fixtures")

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "data"

_FIXTURES: dict[str, dict] = {
    "demo_bistro": {
        "slug": "demo-bistro-eval",
        "name": "Demo Bistro",
        "brand_voice": "Warm, professional, and efficient — like a seasoned maître d'.",
        "timezone": "Europe/London",
        "languages": ["en"],
        "hours": {
            "tuesday": {"open": "17:00", "close": "23:00"},
            "wednesday": {"open": "17:00", "close": "23:00"},
            "thursday": {"open": "17:00", "close": "23:00"},
            "friday": {"open": "17:00", "close": "23:00"},
            "saturday": {"open": "17:00", "close": "23:00"},
            "sunday": {"open": "17:00", "close": "23:00"},
        },
        "config": {
            "covers_per_slot": 20,
            "slot_minutes": 30,
        },
    },
}


async def load_fixture(
    db: AsyncSession,
    fixture_name: str,
    *,
    seed_kb: bool = True,
) -> dict:
    """Load a fixture tenant into the DB and return its metadata.

    Args:
        db: Active async DB session.
        fixture_name: Key into ``_FIXTURES`` (e.g. ``"demo_bistro"``).
        seed_kb: Whether to also ingest the venue's markdown KB file.

    Returns:
        Dict with ``tenant_id``, ``tenant_slug``, ``tenant_name``.

    Raises:
        ValueError: Unknown fixture name.
    """
    spec = _FIXTURES.get(fixture_name)
    if spec is None:
        raise ValueError(
            f"Unknown fixture {fixture_name!r}. "
            f"Available: {list(_FIXTURES)}"
        )

    from app.models import Tenant

    # Check if already seeded (idempotent within the transaction)
    existing = (
        await db.execute(select(Tenant).where(Tenant.slug == spec["slug"]))
    ).scalar_one_or_none()
    if existing is not None:
        return _result(existing)

    tenant = Tenant(
        slug=spec["slug"],
        name=spec["name"],
        brand_voice=spec["brand_voice"],
        timezone=spec["timezone"],
        languages=spec["languages"],
        hours=spec["hours"],
        config=spec["config"],
    )
    db.add(tenant)
    await db.flush()

    if seed_kb:
        await _seed_kb(db, tenant.id, fixture_name)

    log.info("Loaded fixture %r → tenant %s (%s)", fixture_name, tenant.id, tenant.slug)
    return _result(tenant)


async def _seed_kb(db: AsyncSession, tenant_id, fixture_name: str) -> None:
    """Ingest the venue KB markdown into KnowledgeChunk rows."""
    kb_file = FIXTURE_DIR / f"{fixture_name}.md"
    if not kb_file.exists():
        log.warning("KB file not found: %s; skipping KB seeding", kb_file)
        return

    from app.models import KnowledgeChunk

    text = kb_file.read_text(encoding="utf-8")
    # Simple chunking: split by markdown headings (## or #)
    chunks = _chunk_markdown(text)

    for title, content in chunks:
        chunk = KnowledgeChunk(
            tenant_id=tenant_id,
            source=kb_file.name,
            title=title or fixture_name,
            content=content.strip(),
            embedding=None,  # No embedding needed — eval uses replay mode
        )
        db.add(chunk)
    await db.flush()
    log.info("Seeded %d KB chunks for fixture %r", len(chunks), fixture_name)


def _chunk_markdown(text: str) -> list[tuple[str | None, str]]:
    """Split markdown text by headings.

    Returns list of ``(title, content)`` pairs.
    """
    import re

    lines = text.split("\n")
    chunks: list[tuple[str | None, str]] = []
    current_title: str | None = None
    current_lines: list[str] = []

    for line in lines:
        heading_match = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading_match:
            # Save previous chunk
            if current_lines:
                chunks.append((current_title, "\n".join(current_lines)))
            current_title = heading_match.group(2)
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        chunks.append((current_title, "\n".join(current_lines)))

    return chunks


def _result(tenant) -> dict:
    return {
        "tenant_id": str(tenant.id),
        "tenant_slug": tenant.slug,
        "tenant_name": tenant.name,
    }