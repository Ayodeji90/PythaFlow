"""Cross-cutting timezone helpers.

Venue "today" must be computed in the tenant's own timezone. Two callers depend
on this: the system prompt (so the LLM resolves 'tomorrow' / 'this Friday' against
the real current date) and the get_hours tool (so a guest asking "are you open
today?" near a day boundary gets the right day's hours). Computing "today" in UTC
silently gives the wrong answer for any venue west of GMT during late-evening turns.
"""
from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _zone(timezone: str | None) -> ZoneInfo:
    """Resolve a tenant timezone string to a ZoneInfo, falling back to UTC on a
    blank, unknown, or malformed string — a bad tenant config must never break a
    guest turn."""
    try:
        return ZoneInfo(timezone) if timezone else ZoneInfo("UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def venue_now(timezone: str | None) -> datetime.datetime:
    """Current moment in the venue's timezone (tz-aware)."""
    return datetime.datetime.now(_zone(timezone))


def venue_today(timezone: str | None) -> str:
    """Lowercase weekday name for 'today' in the venue's timezone, e.g. 'tuesday'.
    Matches the keys the get_hours tool reads from Tenant.hours."""
    return venue_now(timezone).strftime("%A").lower()
