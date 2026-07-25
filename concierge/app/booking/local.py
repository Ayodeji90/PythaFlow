"""LocalBookingStore — Postgres reservations as the booking backend.

Uses the ``reservations`` table and tenant capacity rules from
``Tenant.config``. Swapped for a real PMS/POS adapter on Day 26+.
"""
from __future__ import annotations

import logging
from datetime import date, time
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ..models.reservation import Reservation
from .availability import compute_availability
from .base import AvailabilityResult, BookingStore, ReservationDraft

log = logging.getLogger("concierge.booking.local")


class LocalBookingStore(BookingStore):
    """Booking backend backed by the Postgres ``reservations`` table."""

    async def check_availability(
        self,
        tenant_id: UUID,
        date: date,
        time: time,
        party_size: int,
        *,
        db: AsyncSession,
    ) -> AvailabilityResult:
        return await compute_availability(tenant_id, date, time, party_size, db=db)

    async def create(
        self,
        tenant_id: UUID,
        draft: ReservationDraft,
        idempotency_key: str,
        ctx: dict[str, Any],
        *,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Create a confirmed Reservation row.

        Called by the fulfilment worker only — NOT by draft_reservation
        (that creates a Request, not a Reservation).
        """
        reservation = Reservation(
            tenant_id=tenant_id,
            guest_id=ctx.get("guest_id"),
            conversation_id=ctx.get("conversation_id"),
            party_size=draft.party_size,
            date=draft.date,
            time=draft.time,
            area=draft.area,
            notes=draft.notes,
            status="pending",
            idempotency_key=idempotency_key,
        )
        db.add(reservation)
        await db.flush()

        return {
            "reservation_id": str(reservation.id),
            "status": "pending",
            "date": str(draft.date),
            "time": draft.time.strftime("%H:%M"),
            "party_size": draft.party_size,
        }