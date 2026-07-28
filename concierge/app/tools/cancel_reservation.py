"""Fulfilment tool: cancels an existing Reservation row after staff approval.

Called by the fulfilment worker ONLY (never by the LLM — hidden via
kind=fulfilment). Uses LocalBookingStore.cancel() which sets status=cancelled.
"""
from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..booking.factory import build_booking_store
from .base import ToolContext, ToolKind


class CancelReservationArgs(BaseModel):
    reservation_id: str = Field(description="UUID of the reservation to cancel")
    reason: str | None = Field(None, description="Optional reason for cancellation")


class CancelReservationTool:
    name = "cancel_reservation"
    description = "Cancel an existing Reservation row after staff approval."
    args_model = CancelReservationArgs
    kind = ToolKind.fulfilment

    async def run(
        self, args: CancelReservationArgs, *, ctx: ToolContext, db: AsyncSession
    ) -> dict:
        store = build_booking_store()
        result = await store.cancel(
            tenant_id=ctx.tenant_id,
            reservation_id=UUID(args.reservation_id),
            reason=args.reason,
            db=db,
        )
        return result


cancel_reservation = CancelReservationTool()