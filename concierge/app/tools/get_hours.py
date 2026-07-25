"""Read-only tool: returns the venue's operating hours for the current day."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.tenant import Tenant
from .base import ToolContext, ToolKind


class GetHoursArgs(BaseModel):
    """No arguments needed — returns today's hours for the venue."""

    pass


class GetHoursTool:
    name: str = "get_hours"
    description: str = "Get the venue's opening hours for today."
    args_model = GetHoursArgs
    kind = ToolKind.read_only

    async def run(
        self, args: GetHoursArgs, *, ctx: ToolContext, db: AsyncSession
    ) -> dict:
        result = await db.execute(
            select(Tenant.hours).where(Tenant.id == ctx.tenant_id)
        )
        hours = result.scalar_one_or_none()
        if not hours:
            return {"hours": None, "message": "No hours configured for this venue."}

        today = datetime.now(datetime.UTC).strftime("%A").lower()
        today_hours = hours.get(today) if isinstance(hours, dict) else hours

        return {"hours": today_hours, "day": today}


get_hours = GetHoursTool()