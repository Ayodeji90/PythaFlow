"""Availability logic — the heart of the booking check.

Given a tenant, date, time, and party size, compute whether the requested
slot can accommodate that party and offer alternatives when it can't.
"""
from __future__ import annotations

import logging
from datetime import date, time
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.reservation import Reservation
from ..models.tenant import Tenant
from .base import AvailabilityResult

log = logging.getLogger("concierge.booking.availability")

# Sensible defaults when Tenant.config is silent.
_DEFAULT_COVERS_PER_SLOT = 20
_DEFAULT_SLOT_MINUTES = 30
_MAX_ALTERNATIVES = 3


async def compute_availability(
    tenant_id: UUID,
    request_date: date,
    request_time: time,
    party_size: int,
    *,
    db: AsyncSession,
) -> AvailabilityResult:
    """Check whether a slot can seat party_size guests.

    Algorithm:
    1. Load Tenant.hours + Tenant.config for capacity rules.
    2. Floor ``request_time`` to the nearest slot boundary (slot_minutes).
    3. Sum ``party_size`` of approved+confirmed reservations whose time falls
       inside [slot_start, slot_end).
    4. Return available=False with up to 3 alternative times when full.
    """
    # --- Load tenant data -------------------------------------------------
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        return AvailabilityResult(available=False)

    config: dict = tenant.config or {}
    hours: dict = tenant.hours or {}
    slot_minutes = config.get("slot_minutes", _DEFAULT_SLOT_MINUTES)
    covers_per_slot = config.get("covers_per_slot", _DEFAULT_COVERS_PER_SLOT)

    # --- Floor time to slot boundary ----------------------------------------
    slot_start = _floor_to_slot(request_time, slot_minutes)
    slot_end = _add_minutes(slot_start, slot_minutes)

    # --- Check operating hours ----------------------------------------------
    day_name = request_date.strftime("%A").lower()
    today_hours: dict[str, str] | None = hours.get(day_name)
    if today_hours:
        try:
            open_t = _parse_time_str(today_hours["open"])
            close_t = _parse_time_str(today_hours["close"])
            if not (open_t <= request_time <= close_t):
                return AvailabilityResult(available=False)
        except (KeyError, ValueError):
            pass  # malformed hours — don't block, fall through to DB check

    # --- Count existing covers in the slot ----------------------------------
    booked = await db.scalar(
        select(func.coalesce(func.sum(Reservation.party_size), 0)).where(
            Reservation.tenant_id == tenant_id,
            Reservation.date == request_date,
            Reservation.status.in_(["approved", "confirmed"]),
            # Reservations whose time falls inside [slot_start, slot_end)
            Reservation.time >= slot_start,
            Reservation.time < slot_end,
        )
    )
    booked = booked or 0

    if booked + party_size <= covers_per_slot:
        return AvailabilityResult(
            available=True, booked_count=booked, remaining=covers_per_slot - booked
        )

    # --- Slot is full — find alternatives -----------------------------------
    alternatives: list[str] = []
    probe = slot_end
    attempts = 0
    max_attempts = slot_minutes * _MAX_ALTERNATIVES * 4  # search up to 12 slots

    while len(alternatives) < _MAX_ALTERNATIVES and attempts < max_attempts:
        probe_start = probe
        probe_end = _add_minutes(probe, slot_minutes)

        # Stop if past close_time
        if today_hours and "close" in today_hours:
            try:
                if _parse_time_str(today_hours["close"]) <= probe_start:
                    break
            except (ValueError, KeyError):
                pass

        alt_booked = await db.scalar(
            select(func.coalesce(func.sum(Reservation.party_size), 0)).where(
                Reservation.tenant_id == tenant_id,
                Reservation.date == request_date,
                Reservation.status.in_(["approved", "confirmed"]),
                Reservation.time >= probe_start,
                Reservation.time < probe_end,
            )
        )
        alt_booked = alt_booked or 0

        if alt_booked + party_size <= covers_per_slot:
            alternatives.append(probe_start.strftime("%H:%M"))

        probe = probe_end
        attempts += 1

    return AvailabilityResult(
        available=False,
        alternatives=alternatives,
        booked_count=booked,
        remaining=covers_per_slot - booked,
    )


def _floor_to_slot(t: time, slot_minutes: int) -> time:
    """Round ``t`` down to the nearest slot boundary."""
    total = t.hour * 60 + t.minute
    floored = (total // slot_minutes) * slot_minutes
    return time(hour=floored // 60, minute=floored % 60)


def _add_minutes(t: time, mins: int) -> time:
    """Return ``t + mins`` — wraps past midnight for alternatives."""
    total = t.hour * 60 + t.minute + mins
    total %= 24 * 60  # wrap
    return time(hour=total // 60, minute=total % 60)


def _parse_time_str(s: str) -> time:
    """Parse 'HH:MM' or 'HH:MM:SS' into a time object."""
    return time.fromisoformat(s.strip())


