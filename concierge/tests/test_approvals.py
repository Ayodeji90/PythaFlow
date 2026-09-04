"""Tests for the Day 10 approval flow: decide(), create_reservation tool,
and the approval router endpoints."""

from __future__ import annotations

import uuid

import pytest

from app.approvals.service import decide
from app.models.enums import (
    ApprovalStatus,
    ChannelType,
    RequestPriority,
    RequestStatus,
    RequestType,
)
from app.models.request import Request
from app.models.tenant import Tenant

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_tenant(session) -> Tenant:
    """Create and return a minimal Tenant row."""
    tenant = Tenant(
        slug=f"t-{uuid.uuid4().hex[:8]}",
        name="Test Venue",
    )
    session.add(tenant)
    await session.flush()
    return tenant


# ---------------------------------------------------------------------------
# decide() — service layer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decide_approves(session):
    """decide() records approval and transitions request."""
    tenant = await _make_tenant(session)
    request = Request(
        tenant_id=tenant.id,
        channel_type=ChannelType.webchat,
        type=RequestType.reservation,
        status=RequestStatus.needs_review,
        summary="Test reservation request",
        payload={"date": "2026-07-25", "time": "20:00", "party_size": 4},
        confidence=0.95,
    )
    session.add(request)
    await session.flush()

    approval = await decide(
        session,
        request.id,
        decision="approved",
    )

    await session.refresh(request)
    assert request.status == RequestStatus.approved
    assert request.decided_at is not None
    assert approval.request_id == request.id
    assert approval.status == ApprovalStatus.approved


@pytest.mark.asyncio
async def test_decide_rejects(session):
    """decide() records rejection and transitions request with note."""
    tenant = await _make_tenant(session)
    request = Request(
        tenant_id=tenant.id,
        channel_type=ChannelType.webchat,
        type=RequestType.reservation,
        status=RequestStatus.needs_review,
        summary="Test rejection",
        payload={},
        confidence=0.95,
    )
    session.add(request)
    await session.flush()

    approval = await decide(
        session,
        request.id,
        decision="rejected",
        note="Table not available",
    )

    await session.refresh(request)
    assert request.status == RequestStatus.rejected
    assert request.resolution == {"note": "Table not available"}
    assert approval.status == ApprovalStatus.rejected


@pytest.mark.asyncio
async def test_decide_invalid_transition(session):
    """decide() raises ValueError if request is already completed."""
    tenant = await _make_tenant(session)
    request = Request(
        tenant_id=tenant.id,
        channel_type=ChannelType.webchat,
        type=RequestType.reservation,
        status=RequestStatus.completed,
        summary="Done request",
        payload={},
        confidence=0.95,
    )
    session.add(request)
    await session.flush()

    with pytest.raises(ValueError, match="not pending"):
        await decide(session, request.id, decision="approved")


@pytest.mark.asyncio
async def test_decide_invalid_decision(session):
    """decide() raises ValueError on unknown decision string."""
    tenant = await _make_tenant(session)
    request = Request(
        tenant_id=tenant.id,
        channel_type=ChannelType.webchat,
        type=RequestType.reservation,
        status=RequestStatus.needs_review,
        summary="Test",
        payload={},
        confidence=0.95,
    )
    session.add(request)
    await session.flush()

    with pytest.raises(ValueError, match="Decision must be"):
        await decide(session, request.id, decision="maybe")


# ---------------------------------------------------------------------------
# create_reservation fulfilment tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_reservation_registered():
    """create_reservation is in the registry as fulfilment."""
    from app.tools.base import ToolKind
    from app.tools.registry import registry

    tool = registry.get("create_reservation")
    assert tool.name == "create_reservation"
    assert tool.kind is ToolKind.fulfilment


@pytest.mark.asyncio
async def test_create_reservation_hidden_from_llm():
    """fulfilment tools must not appear in LLM-facing definitions."""
    from app.tools.registry import registry

    names = [d.name for d in registry.definitions_for()]
    assert "create_reservation" not in names


@pytest.mark.asyncio
async def test_create_reservation_run(session):
    """create_reservation creates a Reservation row via the booking store."""
    from app.models.conversation import Conversation
    from app.models.reservation import Reservation
    from app.tools.base import ToolContext
    from app.tools.create_reservation import CreateReservationArgs
    from app.tools.registry import registry

    tenant = await _make_tenant(session)
    conv = Conversation(tenant_id=tenant.id, channel_type=ChannelType.webchat)
    session.add(conv)
    await session.flush()

    ctx = ToolContext(tenant_id=tenant.id, conversation_id=conv.id)
    tool = registry.get("create_reservation")

    result = await tool.run(
        CreateReservationArgs(
            date="2026-07-25",
            time="20:00",
            party_size=4,
            idempotency_key="test-key-123",
        ),
        ctx=ctx,
        db=session,
    )

    assert "reservation_id" in result
    assert result["status"] == "pending"
    assert result["party_size"] == 4

    # Verify the Reservation row exists
    reservation = await session.get(Reservation, uuid.UUID(result["reservation_id"]))
    assert reservation is not None
    assert reservation.party_size == 4
    assert reservation.idempotency_key == "test-key-123"


# ---------------------------------------------------------------------------
# Approval router endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approval_list_endpoint(session):
    """GET /api/approvals returns pending requests with correct structure."""
    from httpx import ASGITransport, AsyncClient

    from app.deps import get_db
    from app.main import app

    async def _override():
        yield session

    app.dependency_overrides[get_db] = _override

    # Seed a pending request
    tenant = await _make_tenant(session)
    request = Request(
        tenant_id=tenant.id,
        channel_type=ChannelType.webchat,
        type=RequestType.reservation,
        status=RequestStatus.needs_review,
        summary="Weekend booking",
        payload={"date": "2026-07-25"},
        confidence=0.9,
        priority=RequestPriority.normal,
    )
    session.add(request)
    await session.flush()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/approvals", headers={"X-Staff-Token": "dev-token"})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    # Our request should be in the list
    summaries = [r["summary"] for r in data["requests"]]
    assert "Weekend booking" in summaries

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_approval_list_requires_auth():
    """GET /api/approvals without token returns 401."""
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/approvals")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_approval_decide_endpoint(session):
    """POST /api/approvals/decide approves and returns correct response."""
    from httpx import ASGITransport, AsyncClient

    from app.deps import get_db
    from app.main import app

    async def _override():
        yield session

    app.dependency_overrides[get_db] = _override

    # Seed a pending request
    tenant = await _make_tenant(session)
    request = Request(
        tenant_id=tenant.id,
        channel_type=ChannelType.webchat,
        type=RequestType.reservation,
        status=RequestStatus.needs_review,
        summary="Approve me",
        payload={"date": "2026-07-25", "time": "20:00", "party_size": 2},
        confidence=0.95,
    )
    session.add(request)
    await session.flush()
    req_id = str(request.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/approvals/decide",
            headers={"X-Staff-Token": "dev-token"},
            json={"request_id": req_id, "decision": "approved"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["request_id"] == req_id
    assert data["decision"] == "approved"
    assert data["status"] == "fulfilled"

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Modify / Cancel draft + fulfilment tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_draft_modify_registered():
    """draft_modify_reservation is in the registry as draft."""
    from app.tools.base import ToolKind
    from app.tools.registry import registry

    tool = registry.get("draft_modify_reservation")
    assert tool.name == "draft_modify_reservation"
    assert tool.kind is ToolKind.draft


@pytest.mark.asyncio
async def test_draft_cancel_registered():
    """draft_cancel_reservation is in the registry as draft."""
    from app.tools.base import ToolKind
    from app.tools.registry import registry

    tool = registry.get("draft_cancel_reservation")
    assert tool.name == "draft_cancel_reservation"
    assert tool.kind is ToolKind.draft


@pytest.mark.asyncio
async def test_modify_fulfilment_registered():
    """modify_reservation is in the registry as fulfilment."""
    from app.tools.base import ToolKind
    from app.tools.registry import registry

    tool = registry.get("modify_reservation")
    assert tool.name == "modify_reservation"
    assert tool.kind is ToolKind.fulfilment


@pytest.mark.asyncio
async def test_cancel_fulfilment_registered():
    """cancel_reservation is in the registry as fulfilment."""
    from app.tools.base import ToolKind
    from app.tools.registry import registry

    tool = registry.get("cancel_reservation")
    assert tool.name == "cancel_reservation"
    assert tool.kind is ToolKind.fulfilment


@pytest.mark.asyncio
async def test_modify_cancel_hidden_from_llm():
    """fulfilment tools must not appear in LLM-facing definitions."""
    from app.tools.registry import registry

    names = [d.name for d in registry.definitions_for()]
    assert "modify_reservation" not in names
    assert "cancel_reservation" not in names


@pytest.mark.asyncio
async def test_draft_modify_creates_request(session):
    """draft_modify_reservation creates a modification Request."""
    from app.models import Tenant
    from app.models.conversation import Conversation
    from app.models.enums import RequestType
    from app.models.request import Request
    from app.tools.base import ToolContext
    from app.tools.registry import registry

    tenant = Tenant(slug=f"t-{uuid.uuid4().hex[:8]}", name="Test")
    session.add(tenant)
    await session.flush()
    conv = Conversation(tenant_id=tenant.id, channel_type=ChannelType.webchat)
    session.add(conv)
    await session.flush()

    ctx = ToolContext(tenant_id=tenant.id, conversation_id=conv.id)
    tool = registry.get("draft_modify_reservation")

    result = await tool.run(
        tool.args_model(
            reservation_id=str(uuid.uuid4()),
            date="2026-08-01",
            time="19:00",
        ),
        ctx=ctx,
        db=session,
    )

    assert result["status"] == "drafted"
    assert "request_id" in result

    request = await session.get(Request, uuid.UUID(result["request_id"]))
    assert request is not None
    assert request.type == RequestType.modification
    assert request.payload["date"] == "2026-08-01"


@pytest.mark.asyncio
async def test_draft_modify_idempotent(session):
    """Re-drafting same reservation returns existing request."""
    from app.models import Tenant
    from app.models.conversation import Conversation
    from app.tools.base import ToolContext
    from app.tools.registry import registry

    tenant = Tenant(slug=f"t-{uuid.uuid4().hex[:8]}", name="Test")
    session.add(tenant)
    await session.flush()
    conv = Conversation(tenant_id=tenant.id, channel_type=ChannelType.webchat)
    session.add(conv)
    await session.flush()

    res_id = str(uuid.uuid4())
    ctx = ToolContext(tenant_id=tenant.id, conversation_id=conv.id)
    tool = registry.get("draft_modify_reservation")

    first = await tool.run(
        tool.args_model(reservation_id=res_id, date="2026-08-01"),
        ctx=ctx,
        db=session,
    )
    second = await tool.run(
        tool.args_model(reservation_id=res_id, date="2026-08-01"),
        ctx=ctx,
        db=session,
    )

    assert second["status"] == "existing_draft"
    assert second["request_id"] == first["request_id"]


@pytest.mark.asyncio
async def test_draft_cancel_creates_request(session):
    """draft_cancel_reservation creates a cancellation Request."""
    from app.models import Tenant
    from app.models.conversation import Conversation
    from app.models.enums import RequestType
    from app.models.request import Request
    from app.tools.base import ToolContext
    from app.tools.registry import registry

    tenant = Tenant(slug=f"t-{uuid.uuid4().hex[:8]}", name="Test")
    session.add(tenant)
    await session.flush()
    conv = Conversation(tenant_id=tenant.id, channel_type=ChannelType.webchat)
    session.add(conv)
    await session.flush()

    ctx = ToolContext(tenant_id=tenant.id, conversation_id=conv.id)
    tool = registry.get("draft_cancel_reservation")

    result = await tool.run(
        tool.args_model(reservation_id=str(uuid.uuid4()), reason="Guest changed plans"),
        ctx=ctx,
        db=session,
    )

    assert result["status"] == "drafted"
    request = await session.get(Request, uuid.UUID(result["request_id"]))
    assert request is not None
    assert request.type == RequestType.cancellation
    assert request.payload["reason"] == "Guest changed plans"


@pytest.mark.asyncio
async def test_fulfilment_tool_mapping():
    """_fulfilment_tool_name maps all supported RequestTypes correctly."""
    from app.models.enums import RequestType
    from app.requests.fulfilment import _fulfilment_tool_name

    assert _fulfilment_tool_name(RequestType.reservation) == "create_reservation"
    assert _fulfilment_tool_name(RequestType.modification) == "modify_reservation"
    assert _fulfilment_tool_name(RequestType.cancellation) == "cancel_reservation"


@pytest.mark.asyncio
async def test_booking_store_modify(session):
    """LocalBookingStore.modify() updates reservation fields."""
    from datetime import date, time

    from app.booking.base import ModificationDraft
    from app.booking.factory import build_booking_store
    from app.models import Tenant
    from app.models.conversation import Conversation
    from app.models.reservation import Reservation

    tenant = Tenant(slug=f"t-{uuid.uuid4().hex[:8]}", name="Test")
    session.add(tenant)
    await session.flush()
    conv = Conversation(tenant_id=tenant.id, channel_type=ChannelType.webchat)
    session.add(conv)
    await session.flush()

    from app.models.enums import ReservationStatus

    res = Reservation(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        party_size=4,
        date=date(2026, 7, 25),
        time=time(20, 0),
        status=ReservationStatus.pending,
    )
    session.add(res)
    await session.flush()

    store = build_booking_store()
    result = await store.modify(
        tenant_id=tenant.id,
        reservation_id=res.id,
        changes=ModificationDraft(
            reservation_id=str(res.id),
            date="2026-08-01",
            time="19:00",
            party_size=2,
        ),
        db=session,
    )

    assert result["reservation_id"] == str(res.id)
    assert result["date"] == "2026-08-01"

    await session.refresh(res)
    assert res.date == date(2026, 8, 1)
    assert res.party_size == 2


@pytest.mark.asyncio
async def test_booking_store_cancel(session):
    """LocalBookingStore.cancel() sets status to cancelled."""
    from datetime import date, time

    from app.booking.factory import build_booking_store
    from app.models import Tenant
    from app.models.conversation import Conversation
    from app.models.reservation import Reservation

    tenant = Tenant(slug=f"t-{uuid.uuid4().hex[:8]}", name="Test")
    session.add(tenant)
    await session.flush()
    conv = Conversation(tenant_id=tenant.id, channel_type=ChannelType.webchat)
    session.add(conv)
    await session.flush()

    from app.models.enums import ReservationStatus

    res = Reservation(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        party_size=4,
        date=date(2026, 7, 25),
        time=time(20, 0),
        status=ReservationStatus.pending,
    )
    session.add(res)
    await session.flush()

    store = build_booking_store()
    result = await store.cancel(
        tenant_id=tenant.id,
        reservation_id=res.id,
        reason="No longer needed",
        db=session,
    )

    assert result["new_status"] == "cancelled"

    await session.refresh(res)
    assert res.status.value == "cancelled"
