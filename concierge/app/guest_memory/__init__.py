"""Guest memory service: resolves guest identity and stores preferences.

Day 11: web chat is anonymous (no phone/email), so guests are matched by
conversation thread. The service stores extracted preferences (allergies,
seating preferences, occasions) from each turn and makes them available as
system-prompt context for the orchestrator.

Future channels (WhatsApp, email) will provide a phone/email for matching
across conversations.
"""
from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.conversation import Conversation
from ..models.guest import Guest


async def resolve_guest(
    db: AsyncSession,
    tenant_id: UUID,
    conversation_id: UUID,
    *,
    display_name: str | None = None,
    phone: str | None = None,
) -> Guest:
    """Resolve a Guest for this conversation.

    For web chat (anonymous), creates a Guest keyed to the conversation if
    none exists. For channels with identity (WhatsApp, email), resolves or
    links by phone or handle.

    Sets conversation.guest_id if not already set.
    """
    # First, check if the conversation already has a guest linked
    conv_result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conv = conv_result.scalar_one()

    if conv.guest_id:
        result = await db.execute(select(Guest).where(Guest.id == conv.guest_id))
        return result.scalar_one()

    # Try to find by phone (for identified channels)
    if phone:
        result = await db.execute(
            select(Guest).where(
                Guest.tenant_id == tenant_id,
                Guest.phone == phone,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            conv.guest_id = existing.id
            await db.flush()
            return existing

    # Create a new guest
    guest_name = display_name or f"Guest-{conversation_id.hex[:8]}"
    guest = Guest(
        tenant_id=tenant_id,
        display_name=guest_name,
        phone=phone,
        handles={"conversation_id": str(conversation_id)},
        preferences={},
        consent={"memorized_preferences": True},
    )
    db.add(guest)
    await db.flush()

    conv.guest_id = guest.id
    await db.flush()

    return guest


_PREFERENCE_EXTRACTORS: list[tuple[str, str, list[str]]] = [
    ("allergies", "Allergies or dietary restrictions", ["allerg", "dietar", "intoleran", "vegan", "vegetarian"]),
    ("seating", "Seating or area preferences", ["indoor", "outdoor", "terrace", "patio", "bar", "window", "quiet", "table"]),
    ("occasion", "Special occasions being celebrated", ["birthday", "anniversary", "celebrat", "occasion", "propos"]),
    ("accessibility", "Accessibility needs", ["wheelchair", "accessib", "ramp", "stroller"]),
]


def extract_preferences(text: str) -> dict[str, str]:
    """Simple keyword-based preference extraction from a guest message.

    Returns a dict of preference keys -> extracted snippet.
    """
    text_lower = text.lower()
    prefs: dict[str, str] = {}
    for key, label, keywords in _PREFERENCE_EXTRACTORS:
        for kw in keywords:
            if kw in text_lower:
                # Find the sentence containing the keyword
                for sentence in text.split("."):
                    if kw in sentence.lower():
                        prefs[key] = sentence.strip()
                        break
                break
    return prefs


async def update_guest_preferences(
    db: AsyncSession,
    guest_id: UUID,
    extracted: dict[str, str],
) -> None:
    """Merge extracted preferences into the Guest record."""
    if not extracted:
        return

    result = await db.execute(select(Guest).where(Guest.id == guest_id))
    guest = result.scalar_one()

    current = dict(guest.preferences or {})
    changed = False
    for key, value in extracted.items():
        if current.get(key) != value:
            current[key] = value
            changed = True

    if changed:
        guest.preferences = current
        await db.flush()


async def build_guest_context(
    db: AsyncSession,
    tenant_id: UUID,
    conversation_id: UUID,
) -> str | None:
    """Build a context snippet about this guest's known preferences.

    Returns None if no preferences are known yet.
    """
    conv_result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conv = conv_result.scalar_one()
    if not conv.guest_id:
        return None

    result = await db.execute(select(Guest).where(Guest.id == conv.guest_id))
    guest = result.scalar_one()

    if not guest.preferences:
        return None

    lines = [f"  - {k}: {v}" for k, v in guest.preferences.items()]
    return "Known guest preferences:\n" + "\n".join(lines)