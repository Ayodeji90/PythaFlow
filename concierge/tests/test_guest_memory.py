"""Tests for Day 11 guest memory: resolve_guest, extract_preferences,
update_guest_preferences, and build_guest_context."""
from __future__ import annotations

import uuid

import pytest

from app.guest_memory import (
    build_guest_context,
    extract_preferences,
    resolve_guest,
    update_guest_preferences,
)
from app.models.conversation import Conversation
from app.models.enums import ChannelType
from app.models.tenant import Tenant


async def _make_tenant(session) -> Tenant:
    tenant = Tenant(slug=f"t-{uuid.uuid4().hex[:8]}", name="Test Venue")
    session.add(tenant)
    await session.flush()
    return tenant


async def _make_conversation(session, tenant: Tenant) -> Conversation:
    conv = Conversation(tenant_id=tenant.id, channel_type=ChannelType.webchat)
    session.add(conv)
    await session.flush()
    return conv


@pytest.mark.asyncio
async def test_resolve_guest_creates_new(session):
    """resolve_guest creates a new Guest when none exists."""
    tenant = await _make_tenant(session)
    conv = await _make_conversation(session, tenant)

    guest = await resolve_guest(session, tenant.id, conv.id, display_name="Amara")

    assert guest.id is not None
    assert guest.display_name == "Amara"
    assert guest.consent.get("memorized_preferences") is True

    # Conversation should be linked
    await session.refresh(conv)
    assert conv.guest_id == guest.id


@pytest.mark.asyncio
async def test_resolve_guest_reuses_existing(session):
    """resolve_guest returns same guest when conversation already linked."""
    tenant = await _make_tenant(session)
    conv = await _make_conversation(session, tenant)

    first = await resolve_guest(session, tenant.id, conv.id)
    second = await resolve_guest(session, tenant.id, conv.id)

    assert second.id == first.id


@pytest.mark.asyncio
async def test_resolve_guest_by_phone(session):
    """resolve_guest finds existing guest by phone."""
    tenant = await _make_tenant(session)
    conv = await _make_conversation(session, tenant)

    phone = "+234-800-555-0100"
    first = await resolve_guest(session, tenant.id, conv.id, phone=phone)
    assert first.phone == phone

    # A second conversation with same phone links to same guest
    conv2 = await _make_conversation(session, tenant)
    second = await resolve_guest(session, tenant.id, conv2.id, phone=phone)

    assert second.id == first.id


@pytest.mark.asyncio
async def test_extract_preferences_allergies(session):
    """extract_preferences finds allergy keywords."""
    prefs = extract_preferences("I have a peanut allergy, can you accommodate?")
    assert "allergies" in prefs
    assert "peanut" in prefs["allergies"]


@pytest.mark.asyncio
async def test_extract_preferences_occasion(session):
    """extract_preferences finds occasion keywords."""
    prefs = extract_preferences("It's our anniversary, we'd like something special.")
    assert "occasion" in prefs
    assert "anniversary" in prefs["occasion"]


@pytest.mark.asyncio
async def test_extract_preferences_empty(session):
    """extract_preferences returns empty dict for neutral text."""
    prefs = extract_preferences("What are your opening hours?")
    assert prefs == {}


@pytest.mark.asyncio
async def test_update_guest_preferences(session):
    """update_guest_preferences merges into Guest record."""
    tenant = await _make_tenant(session)
    conv = await _make_conversation(session, tenant)

    guest = await resolve_guest(session, tenant.id, conv.id)

    await update_guest_preferences(session, guest.id, {"allergies": "peanut allergy"})

    await session.refresh(guest)
    assert guest.preferences.get("allergies") == "peanut allergy"


@pytest.mark.asyncio
async def test_build_guest_context(session):
    """build_guest_context returns snippet when preferences exist."""
    tenant = await _make_tenant(session)
    conv = await _make_conversation(session, tenant)

    guest = await resolve_guest(session, tenant.id, conv.id)
    await update_guest_preferences(session, guest.id, {"allergies": "peanut allergy"})

    ctx = await build_guest_context(session, tenant.id, conv.id)
    assert ctx is not None
    assert "allergies" in ctx
    assert "peanut" in ctx


@pytest.mark.asyncio
async def test_build_guest_context_no_prefs(session):
    """build_guest_context returns None when no preferences stored."""
    tenant = await _make_tenant(session)
    conv = await _make_conversation(session, tenant)

    await resolve_guest(session, tenant.id, conv.id)
    ctx = await build_guest_context(session, tenant.id, conv.id)
    assert ctx is None