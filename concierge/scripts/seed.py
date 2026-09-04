"""Seed one demo tenant + owner + webchat + email channels. Idempotent — safe
 to re-run.

    uv run python scripts/seed.py

Set TELEGRAM_BOT_TOKEN (optionally TELEGRAM_BOT_USERNAME and
TELEGRAM_WEBHOOK_SECRET) to also provision the demo tenant's Telegram channel.
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Channel, Tenant, User  # noqa: E402
from app.models.enums import ChannelType, UserRole  # noqa: E402


async def _telegram_channel_config() -> dict | None:
    """Bot token from env — the only credential a Telegram bot needs."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return None
    cfg: dict = {"bot_token": token}
    username = os.environ.get("TELEGRAM_BOT_USERNAME", "").strip()
    if username:
        cfg["bot_username"] = username
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if secret:
        cfg["webhook_secret"] = secret
    return cfg


async def _ensure_telegram_channel(s, tenant) -> bool:
    """Create the tenant's Telegram Channel row if a bot token is configured."""
    cfg = await _telegram_channel_config()
    if cfg is None:
        return False
    existing = (
        await s.execute(
            select(Channel).where(
                Channel.tenant_id == tenant.id,
                Channel.type == ChannelType.telegram,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return True
    s.add(
        Channel(
            tenant_id=tenant.id,
            type=ChannelType.telegram,
            external_id=cfg.pop("bot_username", None),
            active=True,
            config=cfg,
        )
    )
    await s.commit()
    print(
        f"✓ added telegram channel for tenant '{tenant.slug}' "
        f"(webhook path: /webhooks/telegram/{tenant.slug})"
    )
    return True


async def main() -> None:
    async with SessionLocal() as s:
        existing = (
            await s.execute(select(Tenant).where(Tenant.slug == "demo"))
        ).scalar_one_or_none()

        if existing:
            # Idempotent: ensure the email channel exists even on re-run.
            email_channel = (
                await s.execute(
                    select(Channel).where(
                        Channel.tenant_id == existing.id,
                        Channel.type == ChannelType.email,
                    )
                )
            ).scalar_one_or_none()
            if not email_channel:
                s.add(
                    Channel(
                        tenant_id=existing.id,
                        type=ChannelType.email,
                        external_id="demo-bistro@getbalance.local",
                        active=True,
                        config={
                            "display_name": "Demo Bistro Concierge",
                            "forward_to": "owner@demo.test",
                        },
                    )
                )
                await s.commit()
                print(
                    f"✓ added email channel for tenant '{existing.slug}' "
                    f"(demo-bistro@getbalance.local)"
                )
            else:
                print(f"tenant '{existing.slug}' already fully seeded — nothing to do")
            # Telegram channel is provisioned on re-runs too (idempotent).
            await _ensure_telegram_channel(s, existing)
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
                external_id="demo-bistro@getbalance.local",
                active=True,
                config={
                    "display_name": "Demo Bistro Concierge",
                    "forward_to": "owner@demo.test",
                },
            ),
        ]
        telegram_cfg = await _telegram_channel_config()
        if telegram_cfg is not None:
            channels.append(
                Channel(
                    tenant_id=tenant.id,
                    type=ChannelType.telegram,
                    external_id=telegram_cfg.pop("bot_username", None),
                    active=True,
                    config=telegram_cfg,
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
        print(
            f"✓ seeded tenant {tenant.id} (slug='demo')"
            f" + owner + webchat channel + email channel"
            + (" + telegram channel" if telegram_cfg is not None else "")
        )


if __name__ == "__main__":
    asyncio.run(main())
