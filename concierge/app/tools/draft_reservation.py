"""Draft tool: creates a Request (reservation, needs_review).

Creates NO Reservation row — the booking only exists after staff approval
(Day 10 fulfilment worker). Idempotent by SHA256 hash so re-drafting the
same slot updates the existing open Request instead of stacking duplicates.
"""
from __future__ import annotations

import hashlib

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.enums import RequestStatus, RequestType
from ..models.request import Request
from .base import ToolContext, ToolKind


class DraftReservationArgs(BaseModel):
    date: str = Field(description="YYYY-MM-DD, e.g. '2026-07-25'")
    time: str = Field(description="HH:MM 24-hour, e.g. '20:00'")
    party_size: int = Field(ge=1, le=50, description="Number of guests")
    area: str | None = Field(None, description="Optional: indoor, terrace, bar, etc.")
    notes: str | None = Field(None, description="Optional guest preference, e.g. 'high chair'")


def _idempotency_key(
    tenant_id: str, conversation_id: str, date_str: str, time_str: str, party_size: int
) -> str:
    """SHA256 digest of the booking identity — consistent across retries."""
    seed = f"{tenant_id}|{conversation_id}|{date_str}|{time_str}|{party_size}"
    return hashlib.sha256(seed.encode()).hexdigest()


class DraftReservationTool:
    name = "draft_reservation"
    description = (
        "Create a draft reservation request for staff review. The booking is "
        "NOT confirmed until a staff member approves it. Use this only after "
        "checking availability. Re-drafting the same booking updates the "
        "existing request instead of creating a duplicate."
    )
    args_model = DraftReservationArgs
    kind = ToolKind.draft

    async def run(
        self, args: DraftReservationArgs, *, ctx: ToolContext, db: AsyncSession
    ) -> dict:
        key = _idempotency_key(
            str(ctx.tenant_id),
            str(ctx.conversation_id),
            args.date,
            args.time,
            args.party_size,
        )

        # --- Check for existing open draft -----------------------------------
        existing = await db.scalars(
            select(Request)
            .where(
                Request.tenant_id == ctx.tenant_id,
                Request.type == RequestType.reservation,
                Request.status.in_([RequestStatus.new, RequestStatus.needs_review]),
            )
            .limit(20)
        )

        for req in existing:
            if req.payload.get("idempotency_key") == key:
                return {
                    "status": "existing_draft",
                    "request_id": str(req.id),
                    "summary": req.summary,
                    "payload": req.payload,
                }

        # --- Create new Request ------------------------------------------------
        request = Request(
            tenant_id=ctx.tenant_id,
            conversation_id=ctx.conversation_id,
            guest_id=ctx.guest_id,
            channel_type=None,
            type=RequestType.reservation,
            status=RequestStatus.needs_review,
            priority="normal",
            summary=f"Table for {args.party_size} on {args.date} at {args.time}",
            payload={
                "date": args.date,
                "time": args.time,
                "party_size": args.party_size,
                "area": args.area,
                "notes": args.notes,
                "idempotency_key": key,
            },
            confidence=0.95,
        )
        db.add(request)
        await db.flush()

        return {
            "status": "drafted",
            "request_id": str(request.id),
            "summary": request.summary,
            "payload": request.payload,
        }


draft_reservation = DraftReservationTool()