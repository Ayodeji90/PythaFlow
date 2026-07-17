"""Seed one demo tenant + owner + webchat channel. Idempotent — safe to re-run.

    uv run python scripts/seed.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Channel, Tenant, User  # noqa: E402
from app.models.enums import ChannelType, UserRole  # noqa: E402


async def main() -> None:
    async with SessionLocal() as s:
        existing = (
            await s.execute(select(Tenant).where(Tenant.slug == "demo"))
        ).scalar_one_or_none()
        if existing:
            print(f"tenant 'demo' already exists ({existing.id}) — nothing to do")
            return

        tenant = Tenant(
            slug="demo",
            name="Demo Bistro",
            brand_voice="Warm, concise, and professional — like a great maître d'.",
            languages=["en"],
            timezone="America/Nassau",
        )
        s.add(tenant)
        await s.flush()  # populate tenant.id

        s.add_all(
            [
                User(
                    tenant_id=tenant.id,
                    email="owner@demo.test",
                    name="Demo Owner",
                    role=UserRole.owner,
                ),
                Channel(
                    tenant_id=tenant.id,
                    type=ChannelType.webchat,
                    external_id="demo-web",
                    active=True,
                ),
            ]
        )
        await s.commit()
        print(f"✓ seeded tenant {tenant.id} (slug='demo') + owner + webchat channel")


if __name__ == "__main__":
    asyncio.run(main())
