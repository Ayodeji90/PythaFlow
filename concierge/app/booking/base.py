"""Booking-store contract — swappable like the LLM seam.

Definitions live at the base so tools import this, never the concrete store.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, time
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession


class AvailabilityResult(BaseModel):
    """What the concierge reports back after checking a slot."""

    available: bool
    alternatives: list[str] = []
    booked_count: int = 0
    remaining: int = 0


class ReservationDraft(BaseModel):
    """Unvalidated draft from the LLM — a booking intent, not a committed row."""

    party_size: int = Field(ge=1, le=50)
    date: date
    time: time
    area: str | None = None
    notes: str | None = None


class ModificationDraft(BaseModel):
    """Fields that may be updated on an existing reservation."""

    reservation_id: str
    party_size: int | None = None
    date: str | None = None
    time: str | None = None
    area: str | None = None
    notes: str | None = None


class BookingStore(ABC):
    """Swappable booking backend.

    LocalBookingStore (Postgres) is the default. On Day 26+ a PMS adapter
    replaces it without any tool or orchestrator changes.
    """

    @abstractmethod
    async def check_availability(
        self,
        tenant_id: UUID,
        date: date,
        time: time,
        party_size: int,
        *,
        db: AsyncSession,
    ) -> AvailabilityResult:
        ...

    @abstractmethod
    async def create(
        self,
        tenant_id: UUID,
        draft: ReservationDraft,
        idempotency_key: str,
        ctx: dict[str, Any],
        *,
        db: AsyncSession,
    ) -> dict[str, Any]:
        ...

    @abstractmethod
    async def modify(
        self,
        tenant_id: UUID,
        reservation_id: UUID,
        changes: ModificationDraft,
        *,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Update an existing reservation's fields."""
        ...

    @abstractmethod
    async def cancel(
        self,
        tenant_id: UUID,
        reservation_id: UUID,
        *,
        reason: str | None = None,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Cancel an existing reservation."""
        ...