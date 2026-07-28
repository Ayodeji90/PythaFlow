"""Fulfilment tool: modifies an existing Reservation row after staff approval.

Called by the fulfilment worker ONLY (never by the LLM — hidden via
kind=fulfilment). Uses LocalBookingStore.modify() which handles the DB update.
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..booking.base import ModificationDraft
from ..booking.factory import build_booking_store
from .base import ToolContext, ToolKind


class ModifyReservationArgs(BaseModel):
    reservation_id: str = Field(description="UUID of the existing reservation to modify")
    date: str | None = Field(None, description="New YYYY-MM-DD")
    time: str | None = Field(None, description="New HH:MM 24-hour")
    party_size: int | None = Field(None, ge=1, le=50, description="New party size")
    area: str | None = Field(None, description="New area")
    notes: str | None = Field(None, description="New notes")


class ModifyReservationTool:
    name = "modify_reservation"
    description = "Modify an existing Reservation row after staff approval."
    args_model = ModifyReservationArgs
    kind = ToolKind.fulfilment

    async def run(
        self, args: ModifyReservationArgs, *, ctx: ToolContext, db: AsyncSession
    ) -> dict:
        store = build_booking_store()
        from uuid import UUID

        draft = ModificationDraft(
            reservation_id=args.reservation_id,
            date=args.date,
            time=args.time,
            party_size=args.party_size,
            area=args.area,
            notes=args.notes,
        )
        result = await store.modify(
            tenant_id=ctx.tenant_id,
            reservation_id=UUID(args.reservation_id),
            changes=draft,
            db=db,
        )
        return result


modify_reservation = ModifyReservationTool()