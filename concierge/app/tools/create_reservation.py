"""Fulfilment tool: creates the actual Reservation row after approval.

Called by the fulfilment worker ONLY (never by the LLM — hidden via
kind=fulfilment). Uses LocalBookingStore.create() which is already tested
and handles idempotency.
"""

from __future__ import annotations

from datetime import date, time

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..booking.base import ReservationDraft
from ..booking.factory import build_booking_store
from .base import ToolContext, ToolKind


class CreateReservationArgs(BaseModel):
    date: str = Field(description="YYYY-MM-DD, e.g. '2026-07-25'")
    time: str = Field(description="HH:MM 24-hour, e.g. '20:00'")
    party_size: int = Field(ge=1, le=50, description="Number of guests")
    area: str | None = Field(default=None, description="Optional: indoor, terrace, bar, etc.")
    notes: str | None = Field(default=None, description="Optional guest preference")
    idempotency_key: str = Field(description="From the draft Request payload — ensures idempotency")


class CreateReservationTool:
    name = "create_reservation"
    description = "Create a confirmed Reservation row after staff approval."
    args_model: type[BaseModel] = CreateReservationArgs
    kind = ToolKind.fulfilment

    async def run(self, args: CreateReservationArgs, *, ctx: ToolContext, db: AsyncSession) -> dict:
        store = build_booking_store()
        draft = ReservationDraft(
            party_size=args.party_size,
            date=date.fromisoformat(args.date),
            time=time.fromisoformat(args.time),
            area=args.area,
            notes=args.notes,
        )
        result = await store.create(
            tenant_id=ctx.tenant_id,
            draft=draft,
            idempotency_key=args.idempotency_key,
            ctx={"guest_id": ctx.guest_id, "conversation_id": ctx.conversation_id},
            db=db,
        )
        return result


create_reservation = CreateReservationTool()
