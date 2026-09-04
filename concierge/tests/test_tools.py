"""Tests for built-in tools (get_hours, etc)."""

from __future__ import annotations

import uuid

import pytest

from app.models.tenant import Tenant
from app.tools import registry
from app.tools.base import ToolContext, ToolKind
from app.tools.get_hours import GetHoursArgs


@pytest.mark.asyncio
async def test_get_hours_registered():
    """get_hours is in the registry as read_only."""
    tool = registry.get("get_hours")
    assert tool.name == "get_hours"
    assert tool.kind is ToolKind.read_only
    assert tool.description


@pytest.mark.asyncio
async def test_get_hours_visible_in_definitions():
    """read_only tools appear in LLM-facing definitions."""
    names = [d.name for d in registry.definitions_for()]
    assert "get_hours" in names


@pytest.mark.asyncio
async def test_get_hours_returns_configured_hours(session):
    """Tool returns the hours stored on the tenant."""
    tenant = Tenant(slug=f"t-{uuid.uuid4().hex[:8]}", name="Hours Test")
    tenant.hours = {"monday": "09:00-17:00", "tuesday": "09:00-17:00"}
    session.add(tenant)
    await session.flush()

    ctx = ToolContext(tenant_id=tenant.id, conversation_id=uuid.uuid4())
    tool = registry.get("get_hours")
    result = await tool.run(GetHoursArgs(), ctx=ctx, db=session)

    assert "hours" in result
    assert "day" in result


@pytest.mark.asyncio
async def test_get_hours_no_hours(session):
    """When Tenant.hours is null the tool returns a friendly message."""
    tenant = Tenant(slug=f"t-{uuid.uuid4().hex[:8]}", name="No Hours")
    tenant.hours = None  # type: ignore[reportAttributeAccessIssue] — SQLAlchemy mapped attr
    # (assigning None clears the hours JSON column; see Tenant model)
    session.add(tenant)
    await session.flush()

    ctx = ToolContext(tenant_id=tenant.id, conversation_id=uuid.uuid4())
    tool = registry.get("get_hours")
    result = await tool.run(GetHoursArgs(), ctx=ctx, db=session)

    assert result["hours"] is None
    assert "No hours" in result["message"]
