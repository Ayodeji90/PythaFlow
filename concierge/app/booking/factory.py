"""Booking-store factory — returns the active backend.

Default: LocalBookingStore. When a PMS/POS adapter is configured (Day 26+),
swap here without touching tools or the orchestrator.
"""

from __future__ import annotations

from .base import BookingStore
from .local import LocalBookingStore


def build_booking_store() -> BookingStore:
    """Return the current booking backend."""
    return LocalBookingStore()
