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
from .base import AvailabilityResult, BookingStore, ModificationDraft, ReservationDraft

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

    async def modify(
        self,
        tenant_id: UUID,
        reservation_id: UUID,
        changes: ModificationDraft,
        *,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Update an existing reservation's mutable fields."""
        from sqlalchemy import select

        result = await db.execute(
            select(Reservation)
            .where(Reservation.id == reservation_id, Reservation.tenant_id == tenant_id)
        )
        reservation = result.scalar_one()
        if changes.date is not None:
            from datetime import date as date_type
            reservation.date = date_type.fromisoformat(changes.date)
        if changes.time is not None:
            from datetime import time as time_type
            reservation.time = time_type.fromisoformat(changes.time)
        if changes.party_size is not None:
            reservation.party_size = changes.party_size
        if changes.area is not None:
            reservation.area = changes.area
        if changes.notes is not None:
            reservation.notes = changes.notes
        await db.flush()

        return {
            "reservation_id": str(reservation.id),
            "status": reservation.status.value if hasattr(reservation.status, 'value') else reservation.status,
            "date": str(reservation.date) if reservation.date else None,
            "time": reservation.time.strftime("%H:%M") if reservation.time else None,
            "party_size": reservation.party_size,
        }

    async def cancel(
        self,
        tenant_id: UUID,
        reservation_id: UUID,
        *,
        reason: str | None = None,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Cancel an existing reservation."""
        from sqlalchemy import select

        from ..models.enums import ReservationStatus

        result = await db.execute(
            select(Reservation)
            .where(Reservation.id == reservation_id, Reservation.tenant_id == tenant_id)
        )
        reservation = result.scalar_one()
        old_status = reservation.status
        reservation.status = ReservationStatus.cancelled
        if reason:
            reservation.notes = (reservation.notes or "") + f"\n[Cancelled: {reason}]"
        await db.flush()

        return {
            "reservation_id": str(reservation.id),
            "old_status": old_status.value if hasattr(old_status, 'value') else old_status,
            "new_status": ReservationStatus.cancelled.value,
            "reason": reason,
        }