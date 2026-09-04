"""Day 9 booking tests — availability, draft, idempotency, safety gates.

Tests use mocked DB sessions so they run without Postgres.
"""

from __future__ import annotations

import uuid
from datetime import date, time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.booking.availability import _add_minutes, _floor_to_slot, compute_availability
from app.booking.base import AvailabilityResult, ReservationDraft
from app.booking.factory import build_booking_store
from app.booking.local import LocalBookingStore
from app.tools.base import ToolContext, ToolKind
from app.tools.check_availability import CheckAvailabilityArgs, check_availability
from app.tools.draft_reservation import (
    DraftReservationArgs,
    _idempotency_key,
    draft_reservation,
)
from app.tools.registry import registry

# ===========================================================================
# Tool registration + safety gate
# ===========================================================================


def test_check_availability_registered():
    tool = registry.get("check_availability")
    assert tool is not None
    assert tool.kind is ToolKind.read_only


def test_draft_reservation_registered():
    tool = registry.get("draft_reservation")
    assert tool is not None
    assert tool.kind is ToolKind.draft


def test_no_fulfilment_in_llm_schema():
    """Fulfilment tools must NOT appear in the schema given to the LLM."""
    schemas = registry.schemas_for(uuid.uuid4())
    for s in schemas:
        tool = registry.get(s["function"]["name"])
        assert tool.kind in (ToolKind.read_only, ToolKind.draft), (
            f"{tool.name} is {tool.kind}, should not be visible to LLM"
        )


def test_all_three_tools_in_schema():
    schemas = registry.schemas_for(uuid.uuid4())
    names = {s["function"]["name"] for s in schemas}
    assert names >= {"get_hours", "check_availability", "draft_reservation"}


# ===========================================================================
# JSON Schema shapes
# ===========================================================================


def test_check_availability_args_schema():
    schema = CheckAvailabilityArgs.model_json_schema()
    props = schema["properties"]
    assert "date" in props
    assert "time" in props
    assert "party_size" in props
    assert props["party_size"]["minimum"] == 1
    assert props["party_size"]["maximum"] == 50


def test_draft_reservation_args_schema():
    schema = DraftReservationArgs.model_json_schema()
    props = schema["properties"]
    assert "date" in props
    assert "time" in props
    assert "party_size" in props
    assert "area" in props
    assert "notes" in props


# ===========================================================================
# Idempotency (pure functions)
# ===========================================================================


def test_idempotency_deterministic():
    k1 = _idempotency_key("tid", "cid", "2026-07-25", "20:00", 4)
    k2 = _idempotency_key("tid", "cid", "2026-07-25", "20:00", 4)
    assert k1 == k2
    assert len(k1) == 64


def test_idempotency_different_inputs():
    k1 = _idempotency_key("tid", "cid", "2026-07-25", "20:00", 4)
    k2 = _idempotency_key("tid", "cid", "2026-07-25", "20:30", 4)
    assert k1 != k2


def test_idempotency_unique_per_tenant():
    k1 = _idempotency_key("t-a", "c1", "2026-07-25", "20:00", 4)
    k2 = _idempotency_key("t-b", "c1", "2026-07-25", "20:00", 4)
    assert k1 != k2


def test_idempotency_unique_per_conversation():
    k1 = _idempotency_key("t1", "c-a", "2026-07-25", "20:00", 4)
    k2 = _idempotency_key("t1", "c-b", "2026-07-25", "20:00", 4)
    assert k1 != k2


# ===========================================================================
# Slot math (pure functions)
# ===========================================================================


def test_floor_to_slot():
    assert _floor_to_slot(time(19, 0), 30) == time(19, 0)
    assert _floor_to_slot(time(19, 15), 30) == time(19, 0)
    assert _floor_to_slot(time(19, 44), 30) == time(19, 30)
    assert _floor_to_slot(time(19, 14), 15) == time(19, 0)
    assert _floor_to_slot(time(19, 29), 60) == time(19, 0)


def test_add_minutes():
    assert _add_minutes(time(19, 0), 30) == time(19, 30)
    assert _add_minutes(time(23, 30), 30) == time(0, 0)
    assert _add_minutes(time(23, 59), 1) == time(0, 0)


# ===========================================================================
# Pydantic models
# ===========================================================================


def test_availability_result_available():
    r = AvailabilityResult(available=True, booked_count=5, remaining=15)
    assert r.available is True
    assert r.alternatives == []


def test_availability_result_full():
    r = AvailabilityResult(
        available=False, alternatives=["20:30", "21:00"], booked_count=20, remaining=0
    )
    assert r.available is False
    assert len(r.alternatives) == 2


def test_draft_valid():
    draft = ReservationDraft(party_size=4, date=date.today(), time=time(20, 0))
    assert draft.party_size == 4


def test_draft_invalid_party_size():
    with pytest.raises(ValidationError):
        ReservationDraft(party_size=0, date=date.today(), time=time(20, 0))


# ===========================================================================
# Factory
# ===========================================================================


def test_factory_returns_local():
    assert isinstance(build_booking_store(), LocalBookingStore)


# ===========================================================================
# Availability computation (mocked DB)
# ===========================================================================


@pytest.mark.asyncio
async def test_compute_availability_tenant_not_found():
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    result = await compute_availability(uuid.uuid4(), date.today(), time(19, 0), 4, db=db)
    assert result.available is False


@pytest.mark.asyncio
async def test_compute_availability_available():
    """Slot has capacity: booked + party <= covers_per_slot."""
    from app.models.tenant import Tenant

    tenant = Tenant(
        id=uuid.uuid4(),
        slug="test",
        name="Test Bistro",
        timezone="UTC",
        hours={},
        config={"covers_per_slot": 20, "slot_minutes": 30},
    )

    db = AsyncMock()
    db.get = AsyncMock(return_value=tenant)
    db.scalar = AsyncMock(return_value=8)

    result = await compute_availability(tenant.id, date.today(), time(19, 0), 4, db=db)
    assert result.available is True
    assert result.booked_count == 8
    assert result.remaining == 12


@pytest.mark.asyncio
async def test_compute_availability_full():
    """Slot is full: booked + party > capacity."""
    from app.models.tenant import Tenant

    tenant = Tenant(
        id=uuid.uuid4(),
        slug="full",
        name="Full",
        timezone="UTC",
        hours={},
        config={"covers_per_slot": 10, "slot_minutes": 30},
    )

    db = AsyncMock()
    db.get = AsyncMock(return_value=tenant)
    db.scalar = AsyncMock(side_effect=[10, 0, 0, 0])

    result = await compute_availability(tenant.id, date.today(), time(19, 0), 4, db=db)
    assert result.available is False
    assert result.booked_count == 10
    assert len(result.alternatives) <= 3


# ===========================================================================
# Check-availability tool (mocked store)
# ===========================================================================


@pytest.mark.asyncio
async def test_check_availability_tool():
    ctx = ToolContext(tenant_id=uuid.uuid4(), conversation_id=uuid.uuid4())
    db = AsyncMock()
    mock_result = AvailabilityResult(available=True, booked_count=3, remaining=17)

    with patch.object(LocalBookingStore, "check_availability", AsyncMock(return_value=mock_result)):
        result = await check_availability.run(
            CheckAvailabilityArgs(date="2026-07-25", time="20:00", party_size=4),
            ctx=ctx,
            db=db,
        )

    assert result["available"] is True
    assert result["booked_count"] == 3


# ===========================================================================
# Draft-reservation tool (mocked DB)
# ===========================================================================


@pytest.mark.asyncio
async def test_draft_reservation_creates_request():
    """Draft creates a Request and calls db.add."""
    ctx = ToolContext(tenant_id=uuid.uuid4(), conversation_id=uuid.uuid4())
    db = AsyncMock()
    db.scalars = AsyncMock(return_value=[])
    db.add = MagicMock()
    db.flush = AsyncMock()

    result = await draft_reservation.run(
        DraftReservationArgs(date="2026-07-25", time="20:00", party_size=4),
        ctx=ctx,
        db=db,
    )

    assert result["status"] == "drafted"
    assert result["request_id"] is not None
    assert "Table for 4" in result["summary"]
    assert "idempotency_key" in result["payload"]
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_draft_reservation_existing_draft():
    """Same booking twice returns existing_draft."""
    ctx = ToolContext(tenant_id=uuid.uuid4(), conversation_id=uuid.uuid4())

    # Pre-compute the key so we can match it
    key = _idempotency_key(str(ctx.tenant_id), str(ctx.conversation_id), "2026-07-25", "20:00", 4)

    existing = MagicMock()
    existing.id = uuid.uuid4()
    existing.summary = "Table for 4 on 2026-07-25 at 20:00"
    existing.payload = {
        "date": "2026-07-25",
        "time": "20:00",
        "party_size": 4,
        "idempotency_key": key,
    }

    db = AsyncMock()
    db.scalars = AsyncMock(return_value=[existing])

    result = await draft_reservation.run(
        DraftReservationArgs(date="2026-07-25", time="20:00", party_size=4),
        ctx=ctx,
        db=db,
    )

    assert result["status"] == "existing_draft"
    assert result["request_id"] == str(existing.id)
