"""Read-only tool: check table availability for a date/time/party size.

The LLM calls this freely mid-chat so it can say "8:00 is full, but 8:30
works?" without touching any write path.
"""
from __future__ import annotations

from datetime import date, time

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..booking.factory import build_booking_store
from .base import ToolContext, ToolKind


class CheckAvailabilityArgs(BaseModel):
    date: str = Field(description="Date in YYYY-MM-DD format, e.g. '2026-07-25'")
    time: str = Field(description="Time in HH:MM 24-hour format, e.g. '20:00'")
    party_size: int = Field(ge=1, le=50, description="Number of guests")


class CheckAvailabilityTool:
    name = "check_availability"
    description = (
        "Check whether there is capacity at the venue on a given date and time "
        "for the requested party size. Returns whether the slot is available, "
        "how many covers are already booked, and up to 3 alternative times when "
        "the requested slot is full."
    )
    args_model = CheckAvailabilityArgs
    kind = ToolKind.read_only

    async def run(
        self, args: CheckAvailabilityArgs, *, ctx: ToolContext, db: AsyncSession
    ) -> dict:
        store = build_booking_store()
        result = await store.check_availability(
            tenant_id=ctx.tenant_id,
            date=date.fromisoformat(args.date),
            time=time.fromisoformat(args.time),
            party_size=args.party_size,
            db=db,
        )
        return result.model_dump()


check_availability = CheckAvailabilityTool()