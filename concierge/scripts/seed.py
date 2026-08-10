"""Seed one demo tenant + owner + webchat channel. Idempotent — safe to re-run.

    uv run python scripts/seed.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Channel, Tenant, User  # noqa: E402
from app.models.enums import ChannelType, UserRole  # noqa: E402


async def _ensure_channel(
    s, tenant_id, *, type: ChannelType, external_id: str, config: dict | None = None
) -> bool:
    """Create a channel if missing; return True when newly created."""
    existing = (
        await s.execute(
            select(Channel).where(
                Channel.tenant_id == tenant_id,
                Channel.type == type,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return False
    s.add(
        Channel(
            tenant_id=tenant_id,
            type=type,
            external_id=external_id,
            active=True,
            config=config,
        )
    )
    return True


async def main() -> None:
    async with SessionLocal() as s:
        settings = get_settings()
        existing = (
            await s.execute(select(Tenant).where(Tenant.slug == "demo"))
        ).scalar_one_or_none()

        if existing:
            # Idempotent: ensure channels exist even on re-run.
            added_email = await _ensure_channel(
                s,
                existing.id,
                type=ChannelType.email,
                external_id="demo-bistro@pythaflow.local",
                config={
                    "display_name": "Demo Bistro Concierge",
                    "forward_to": "owner@demo.test",
                },
            )
            added_wa = False
            if settings.WHATSAPP_PHONE_ID:
                added_wa = await _ensure_channel(
                    s,
                    existing.id,
                    type=ChannelType.whatsapp,
                    external_id=settings.WHATSAPP_PHONE_ID,
                    config={"display_name": "Demo Bistro on WhatsApp"},
                )
            if added_email or added_wa:
                await s.commit()
                print(f"✓ added missing channels for tenant '{existing.slug}'")
            else:
                print(f"tenant '{existing.slug}' already fully seeded — nothing to do")
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

        channels = [
            Channel(
                tenant_id=tenant.id,
                type=ChannelType.webchat,
                external_id="demo-web",
                active=True,
            ),
            Channel(
                tenant_id=tenant.id,
                type=ChannelType.email,
                external_id="demo-bistro@pythaflow.local",
                active=True,
                config={
                    "display_name": "Demo Bistro Concierge",
                    "forward_to": "owner@demo.test",
                },
            ),
        ]
        if settings.WHATSAPP_PHONE_ID:
            channels.append(
                Channel(
                    tenant_id=tenant.id,
                    type=ChannelType.whatsapp,
                    external_id=settings.WHATSAPP_PHONE_ID,
                    config={"display_name": "Demo Bistro on WhatsApp"},
                )
            )
        s.add_all(
            [
                User(
                    tenant_id=tenant.id,
                    email="owner@demo.test",
                    name="Demo Owner",
                    role=UserRole.owner,
                ),
                *channels,
            ]
        )
        await s.commit()
        channel_names = " + ".join(c.type.value for c in channels)
        print(
            f"✓ seeded tenant {tenant.id} (slug='demo')"
            f" + owner + {channel_names} channels"
        )


if __name__ == "__main__":
    asyncio.run(main())
