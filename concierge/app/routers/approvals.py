"""Staff approval endpoints: review and decide on pending Requests.

- GET  /api/approvals       — list pending requests
- POST /api/approvals/decide — approve or reject a request

Auth uses the X-Staff-Token header (matching STAFF_TOKEN_HEADER in config).
For dev environments any non-empty token is accepted.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..approvals.service import decide
from ..audit import actor_from_token, record_audit
from ..deps import get_db, resolve_tenant_or_404
from ..llm.factory import build_llm_service
from ..models import Guest
from ..models.enums import RequestStatus, RequestType
from ..models.request import Request
from ..notifications import NOTIF_REQUEST_APPROVED, NOTIF_REQUEST_REJECTED, notify
from ..requests.fulfilment import fulfil_request
from ..schemas.approval import (
    ApprovalQueueItem,
    ApprovalQueueResponse,
    DecideRequest,
    DecideResponse,
    EditRequest,
    EditResponse,
)
from .console_auth import require_staff_token

log = logging.getLogger("concierge.routers.approvals")

router = APIRouter()


@router.get("/api/approvals", response_model=ApprovalQueueResponse)
async def list_approvals(
    tenant: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_staff_token),
) -> ApprovalQueueResponse:
    """List pending Requests (needs_review + new), newest first.

    Day 18: an optional ``tenant`` slug scopes the queue (the console always
    passes it); items carry the channel badge + guest name for the designer
    mock. Without ``tenant`` it returns all tenants' pending requests (the
    Week-2 single-tenant behaviour, kept for backwards compatibility).
    """
    stmt = select(Request).where(
        Request.status.in_([RequestStatus.needs_review, RequestStatus.new])
    )
    if tenant:
        t = await resolve_tenant_or_404(db, tenant)
        stmt = stmt.where(Request.tenant_id == t.id)
    result = await db.execute(stmt.order_by(Request.created_at.desc()))
    requests = result.scalars().all()

    items: list[ApprovalQueueItem] = []
    for r in requests:
        guest = await db.get(Guest, r.guest_id) if r.guest_id else None
        items.append(
            ApprovalQueueItem(
                request_id=r.id,
                type=r.type.value,
                summary=r.summary,
                confidence=r.confidence,
                priority=r.priority.value,
                status=r.status.value,
                created_at=r.created_at,
                conversation_id=r.conversation_id,
                channel_type=r.channel_type.value if r.channel_type else None,
                guest_name=guest.display_name if guest else None,
                payload=r.payload or {},
            )
        )
    return ApprovalQueueResponse(requests=items, total=len(items))


@router.post("/api/approvals/decide", response_model=DecideResponse)
async def decide_approval(
    body: DecideRequest,
    token: str = Depends(require_staff_token),
    db: AsyncSession = Depends(get_db),
) -> DecideResponse:
    """Approve or reject a pending Request.

    On approval: records the decision, triggers fulfilment (creates the
    Reservation row), then notifies. On rejection: records the decision
    with an optional note, then notifies. Every decision is audited.
    """
    actor = actor_from_token(token)
    try:
        approval = await decide(
            db,
            body.request_id,
            decision=body.decision,
            note=body.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if body.decision == "approved":
        llm = build_llm_service()
        await fulfil_request(db, body.request_id, llm=llm)
        await record_audit(
            db,
            tenant_id=approval.tenant_id,
            conversation_id=None,
            action="approve",
            actor=actor,
            detail={"request_id": str(body.request_id), "note": body.note},
        )
        await db.commit()
        await notify(
            NOTIF_REQUEST_APPROVED,
            tenant_id=approval.tenant_id,
            request_id=body.request_id,
            payload={"note": body.note} if body.note else {},
        )
        return DecideResponse(
            request_id=body.request_id,
            decision="approved",
            status="fulfilled",
        )
    else:
        await record_audit(
            db,
            tenant_id=approval.tenant_id,
            conversation_id=None,
            action="reject",
            actor=actor,
            detail={"request_id": str(body.request_id), "note": body.note},
        )
        await db.commit()
        await notify(
            NOTIF_REQUEST_REJECTED,
            tenant_id=approval.tenant_id,
            request_id=body.request_id,
            payload={"note": body.note} if body.note else {},
        )
        return DecideResponse(
            request_id=body.request_id,
            decision="rejected",
            status="rejected",
        )


@router.patch("/api/requests/{request_id}", response_model=EditResponse)
async def edit_request(
    request_id: UUID,
    body: EditRequest,
    tenant: str = Query(...),
    token: str = Depends(require_staff_token),
    db: AsyncSession = Depends(get_db),
) -> EditResponse:
    """Edit-before-approve (Day 18): fix what the AI misheard.

    Only pending Requests (new|needs_review) are editable. The change lands in
    ``Request.payload`` (what fulfilment reads) AND is snapshotted into
    ``Request.resolution`` — a recorded edit, never a silent overwrite.
    """
    t = await resolve_tenant_or_404(db, tenant)
    request = await db.get(Request, request_id)
    if request is None or request.tenant_id != t.id:
        raise HTTPException(status_code=404, detail="request not found")
    if request.status not in (RequestStatus.new, RequestStatus.needs_review):
        raise HTTPException(status_code=400, detail="only pending requests are editable")

    payload = dict(request.payload or {})
    edits = body.model_dump(exclude_none=True)
    for key, value in edits.items():
        payload[key] = value
    request.payload = payload
    if request.type == RequestType.reservation:
        # Only reservation requests have a booking-shaped summary; a
        # modification/cancellation payload (reservation_id, no date/time)
        # must not be mangled into "Table for None on None at None".
        request.summary = (
            f"Table for {payload.get('party_size')} on {payload.get('date')} "
            f"at {payload.get('time')}"
        )
    elif edits:
        request.summary = f"{request.summary or request.type.value} (edited)"
    edited_at = datetime.now(UTC)
    request.resolution = {
        **dict(request.resolution or {}),
        "edited": edits,
        "edited_at": edited_at.isoformat(),
        "edited_by": actor_from_token(token),
    }
    await record_audit(
        db,
        tenant_id=t.id,
        conversation_id=request.conversation_id,
        action="edit",
        actor=actor_from_token(token),
        detail={"request_id": str(request.id), "edited": edits},
    )
    await db.commit()
    return EditResponse(
        request_id=request.id,
        summary=request.summary or "",
        payload=payload,
        edited_at=edited_at,
    )