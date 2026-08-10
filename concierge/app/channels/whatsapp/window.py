"""Meta's 24-hour service window (Day 16).

Inside the 24h window since the guest's last inbound message, a business may
send **free-form text** (a "service" message) at no cost. Outside it, outbound
messages *must* use an approved template — free-form text is silently dropped
by Meta. This module is the single place that decision lives so every outbound
path (reply, confirmation, reminder) behaves the same way.

Week-3 risk 4 is enforced here: an out-of-window send with **no** approved
template raises — the caller must treat that as a loud error, never a quiet
drop.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

SERVICE_WINDOW_HOURS = 24
SERVICE_WINDOW = timedelta(hours=SERVICE_WINDOW_HOURS)


def _ensure_utc(dt: datetime) -> datetime:
    """Treat naive datetimes as UTC so the comparison is always safe."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def within_service_window(
    last_inbound_at: datetime | None,
    now: datetime | None = None,
) -> bool:
    """True when `now` is within SERVICE_WINDOW of the guest's last message.

    A conversation with no inbound message yet is treated as **out** of window,
    so proactive sends (confirmations/reminders) use a template.
    """
    if last_inbound_at is None:
        return False
    if now is None:
        now = datetime.now(UTC)
    return now - _ensure_utc(last_inbound_at) < SERVICE_WINDOW


def choose_send_mode(
    last_inbound_at: datetime | None,
    template_name: str | None,
    now: datetime | None = None,
) -> str:
    """Pick ``"text"`` (in-window free-form) or ``"template"`` (out-of-window).

    Raises ``ValueError`` when out of window **and** no template is available —
    the Week-3 rule: loud error, never a silent drop.
    """
    if within_service_window(last_inbound_at, now):
        return "text"
    if template_name:
        return "template"
    raise ValueError(
        "out of the 24h service window with no approved template — refusing to "
        "send free-form text (Meta would silently drop it)"
    )
