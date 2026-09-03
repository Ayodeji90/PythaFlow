"""Reminder service — lightweight async scheduler for booking reminders.

Scans for upcoming reservations at a configurable interval and dispatches
notifications via the notification system. Runs as an asyncio background task
attached to the application lifespan.

Day 12 upgrade: Redis ZADD/ZRANGEBYSCORE for efficient due-queue (vs full DB scan).
Falls back to DB scan when Redis is unavailable.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from ..models.enums import ReservationStatus
from ..models.reservation import Reservation
from ..notifications import NOTIF_MESSAGE_SENT, notify

log = logging.getLogger("concierge.reminders")

# How far ahead to fire a reminder (e.g. 2 hours before the booking)
REMINDER_LEAD_HOURS = 2
# How often the scheduler wakes up to check (seconds)
SCHEDULER_INTERVAL_SECONDS = 60
# Redis key prefix for reminder sorted sets: reminders:{tenant_id}
_REDIS_KEY_TPL = "reminders:{}"
# In-memory dedup set (when Redis is unavailable)
_reminded_set: set[str] = set()

# E2: Lua script for atomic ZRANGEBYSCORE + ZREM.
# Returns the removed members so the caller can fire them.
# This prevents double-firing under multi-worker deployments.
_ATOMIC_POP_LUA = """
local key = KEYS[1]
local max_score = tonumber(ARGV[1])
local items = redis.call('ZRANGEBYSCORE', key, 0, max_score)
if #items > 0 then
    redis.call('ZREM', key, unpack(items))
end
return items
"""


async def schedule_reminder(
    redis,
    *,
    tenant_id: str,
    reservation_id: str,
    booking_dt: datetime,
) -> bool:
    """Schedule a reminder via Redis ZADD for N hours before the booking.

    Returns True on success, False if Redis is unavailable (caller should
    fall back to in-memory tracking).
    """
    if redis is None:
        return False
    due_ts = booking_dt.timestamp() - (REMINDER_LEAD_HOURS * 3600)
    key = _REDIS_KEY_TPL.format(tenant_id)
    member = str(reservation_id)
    try:
        await redis.zadd(key, {member: due_ts})
        log.info("Scheduled reminder for reservation %s at %s", member, booking_dt)
        return True
    except Exception:
        log.exception("Failed to schedule reminder via Redis")
        return False


async def _check_and_fire(
    db_session_factory,
    redis=None,
) -> None:
    """One scan cycle: find upcoming reservations and fire reminders.

    Primary source: Redis ZRANGEBYSCORE (tenant-scoped sorted sets).
    Fallback: DB full scan for confirmed reservations in the reminder window.
    """

    now = datetime.now(UTC)
    window_end_ts = now.timestamp() + (SCHEDULER_INTERVAL_SECONDS * 2)

    fired: set[str] = set()

    # --- Primary: Redis atomic pop (E2 fix) ---
    # Uses a Lua script for atomic ZRANGEBYSCORE + ZREM so multi-worker
    # deployments never double-fire the same reminder.
    if redis is not None:
        try:
            _pop_script = redis.register_script(_ATOMIC_POP_LUA)
            cursor = 0
            while True:
                cursor, keys = await redis.scan(cursor, match="reminders:*", count=100)
                for key in keys:
                    # Atomic: get due items AND remove them in one operation
                    due_items = await _pop_script(keys=[key], args=[window_end_ts])
                    if not due_items:
                        continue
                    tenant_id = key.split(":", 1)[1]
                    for member_bytes in due_items:
                        member = str(member_bytes)
                        res_id = member
                        # Fire the reminder
                        log.info("Firing reminder for reservation %s", res_id)
                        await notify(
                            NOTIF_MESSAGE_SENT,
                            tenant_id=tenant_id,
                            request_id=None,
                            payload={
                                "subject": "reminder",
                                "reservation_id": res_id,
                                "message": (
                                        f"Reminder: you have a reservation "
                                        f"in about {REMINDER_LEAD_HOURS} hours."
                                    ),
                            },
                        )
                        fired.add(res_id)
                if cursor == 0:
                    break
        except Exception:
            log.exception("Redis reminder scan failed; falling back to DB scan")
            # Fall through to DB scan below
        else:
            # Remove fired from in-memory set if they were tracked there
            _reminded_set.difference_update(fired)
            if fired:
                return  # Done for this cycle

    # --- Fallback: DB full scan ---
    async with db_session_factory() as db:
        window_start = now + timedelta(hours=REMINDER_LEAD_HOURS - 0.5)
        window_end = now + timedelta(hours=REMINDER_LEAD_HOURS + 0.5)

        result = await db.execute(
            select(Reservation)
            .filter(Reservation.status == ReservationStatus.confirmed)
            .filter(Reservation.date.isnot(None))
            .filter(Reservation.time.isnot(None))
        )
        rows = result.scalars().all()

        for res in rows:
            if not res.date or not res.time:
                continue
            booking_dt = datetime.combine(res.date, res.time, tzinfo=UTC)
            if window_start <= booking_dt <= window_end:
                key = str(res.id)
                if key not in _reminded_set:
                    _reminded_set.add(key)
                    log.info("Firing reminder (DB fallback) for reservation %s", key)
                    await notify(
                        NOTIF_MESSAGE_SENT,
                        tenant_id=res.tenant_id,
                        request_id=None,
                        payload={
                            "subject": "reminder",
                            "reservation_id": key,
                            "message": (
                                        f"Reminder: you have a reservation "
                                        f"in about {REMINDER_LEAD_HOURS} hours."
                                    ),
                        },
                    )


async def run_scheduler(db_session_factory, redis=None) -> None:
    """Run the reminder scheduler loop as a background task.

    Attach this to the application lifespan:
        reminder_task = asyncio.create_task(run_scheduler(SessionLocal, redis_client))
    """
    log.info(
        "Reminder scheduler started (interval=%ss, lead=%sh, redis=%s)",
        SCHEDULER_INTERVAL_SECONDS,
        REMINDER_LEAD_HOURS,
        redis is not None,
    )
    while True:
        try:
            await _check_and_fire(db_session_factory, redis=redis)
        except Exception:  # noqa: BLE001 — scheduler must never crash
            log.exception("Reminder check cycle failed")
        await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)