"""Booking subsystem — swappable persistence seam for reservations.

Today: LocalBookingStore (Postgres reservations table + tenant capacity).
Day 26+: swap to a real PMS/POS without touching tools.
"""

from .base import AvailabilityResult, BookingStore, ReservationDraft

__all__ = ["AvailabilityResult", "BookingStore", "ReservationDraft"]
