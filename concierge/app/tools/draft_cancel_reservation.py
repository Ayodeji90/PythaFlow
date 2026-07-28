"""Draft tool: creates a Request (cancellation, needs_review).

Creates NO actual cancellation — the reservation is only cancelled after staff
approval (Day 10 fulfilment worker). Idempotent by reservation_id.
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.enums import RequestStatus, RequestType
from ..models.request import Request
from .base import ToolContext, ToolKind


class DraftCancelReservationArgs(BaseModel):
    reservation_id: str = Field(description="UUID of the reservation to cancel")
    reason: str | None = Field(None, description="Optional reason for cancellation")


class DraftCancelReservationTool:
    name = "draft_cancel_reservation"
    description = (
        "Create a draft cancellation request for staff review. The reservation "
        "is NOT cancelled until a staff member approves it. Use this when a guest "
        "wants to cancel an existing booking. Re-drafting cancellation for the same "
        "reservation updates the existing request instead of creating a duplicate."
    )
    args_model = DraftCancelReservationArgs
    kind = ToolKind.draft

    async def run(
        self, args: DraftCancelReservationArgs, *, ctx: ToolContext, db: AsyncSession
    ) -> dict:
        # --- Check for existing open draft for this reservation ---------------
        existing = await db.scalars(
            select(Request)
            .where(
                Request.tenant_id == ctx.tenant_id,
                Request.type == RequestType.cancellation,
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

        summary = (
            f"Cancel reservation {args.reservation_id[:8]}…"
            + (f" — {args.reason}" if args.reason else "")
        )

        request = Request(
            tenant_id=ctx.tenant_id,
            conversation_id=ctx.conversation_id,
            guest_id=ctx.guest_id,
            channel_type=ctx.channel_type,
            type=RequestType.cancellation,
            status=RequestStatus.needs_review,
            priority="normal",
            summary=summary,
            payload={
                "reservation_id": args.reservation_id,
                "reason": args.reason,
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


draft_cancel_reservation = DraftCancelReservationTool()