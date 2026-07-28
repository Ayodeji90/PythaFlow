"""Draft tool: creates a Request (modification, needs_review).

Creates NO actual changes to the Reservation — the modification only happens
after staff approval (Day 10 fulfilment worker). Idempotent by reservation_id
so re-drafting the same modification updates the existing open Request.
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.enums import RequestStatus, RequestType
from ..models.request import Request
from .base import ToolContext, ToolKind


class DraftModifyReservationArgs(BaseModel):
    reservation_id: str = Field(description="UUID of the existing reservation to modify")
    date: str | None = Field(None, description="New YYYY-MM-DD, e.g. '2026-07-25'")
    time: str | None = Field(None, description="New HH:MM 24-hour, e.g. '21:00'")
    party_size: int | None = Field(None, ge=1, le=50, description="New party size")
    area: str | None = Field(None, description="New area: indoor, terrace, bar, etc.")
    notes: str | None = Field(None, description="New notes or preferences")


class DraftModifyReservationTool:
    name = "draft_modify_reservation"
    description = (
        "Create a draft modification request for staff review. The reservation "
        "is NOT changed until a staff member approves it. Use this when a guest "
        "wants to change an existing booking's date, time, party size, area, or notes. "
        "Re-drafting the same modification updates the existing request instead of "
        "creating a duplicate."
    )
    args_model = DraftModifyReservationArgs
    kind = ToolKind.draft

    async def run(
        self, args: DraftModifyReservationArgs, *, ctx: ToolContext, db: AsyncSession
    ) -> dict:
        # --- Check for existing open draft for this reservation ---------------
        existing = await db.scalars(
            select(Request)
            .where(
                Request.tenant_id == ctx.tenant_id,
                Request.type == RequestType.modification,
                Request.status.in_([RequestStatus.new, RequestStatus.needs_review]),
            )
            .limit(20)
        )

        for req in existing:
            if req.payload.get("reservation_id") == args.reservation_id:
                return {
                    "status": "existing_draft",
                    "request_id": str(req.id),
                    "summary": req.summary,
                    "payload": req.payload,
                }

        # --- Build summary ------------------------------------------------
        changed = []
        if args.date:
            changed.append(f"date={args.date}")
        if args.time:
            changed.append(f"time={args.time}")
        if args.party_size:
            changed.append(f"party={args.party_size}")
        if args.area:
            changed.append(f"area={args.area}")
        summary = f"Modify reservation {args.reservation_id[:8]}… ({', '.join(changed)})"

        # --- Create new Request ------------------------------------------
        request = Request(
            tenant_id=ctx.tenant_id,
            conversation_id=ctx.conversation_id,
            guest_id=ctx.guest_id,
            channel_type=ctx.channel_type,
            type=RequestType.modification,
            status=RequestStatus.needs_review,
            priority="normal",
            summary=summary,
            payload={
                "reservation_id": args.reservation_id,
                "date": args.date,
                "time": args.time,
                "party_size": args.party_size,
                "area": args.area,
                "notes": args.notes,
            },
            confidence=0.90,
        )
        db.add(request)
        await db.flush()

        return {
            "status": "drafted",
            "request_id": str(request.id),
            "summary": request.summary,
            "payload": request.payload,
        }


draft_modify_reservation = DraftModifyReservationTool()