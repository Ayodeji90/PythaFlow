"""Ingest a text/markdown file into a tenant's knowledge base.

    uv run python scripts/ingest_kb.py --tenant demo --source hours data/hours.md
    uv run python scripts/ingest_kb.py --tenant demo path/to/venue.md   # source = filename
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.knowledge.ingest import ingest_text  # noqa: E402
from app.models import Tenant  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", type=Path)
    ap.add_argument("--tenant", required=True, help="tenant slug")
    ap.add_argument("--source", help="source id (default: file name)")
    ap.add_argument("--title", help="optional base title for the chunks")
    args = ap.parse_args()

    if not args.file.exists():
        print(f"file not found: {args.file}")
        return 1
    text = args.file.read_text(encoding="utf-8")
    source = args.source or args.file.name

    async with SessionLocal() as db:
        tenant = (
            await db.execute(select(Tenant).where(Tenant.slug == args.tenant))
        ).scalar_one_or_none()
        if tenant is None:
            print(f"unknown tenant '{args.tenant}' — run scripts/seed.py first?")
            return 1
        result = await ingest_text(
            db, tenant_id=tenant.id, source=source, text=text, title=args.title
        )
    print(f"✓ ingested {result.chunks} chunks from '{source}' into tenant '{args.tenant}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
