"""Staff approval endpoints: review and decide on pending Requests.

- GET  /api/approvals       — list pending requests
- POST /api/approvals/decide — approve or reject a request

Auth uses the X-Staff-Token header (matching STAFF_TOKEN_HEADER in config).
For dev environments any non-empty token is accepted.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..approvals.service import decide
from ..config import get_settings
from ..deps import get_db
from ..llm.factory import build_llm_service
from ..models.enums import RequestStatus
from ..models.request import Request
from ..notifications import NOTIF_REQUEST_APPROVED, NOTIF_REQUEST_REJECTED, notify
from ..requests.fulfilment import fulfil_request
from ..schemas.approval import (
    ApprovalQueueItem,
    ApprovalQueueResponse,
    DecideRequest,
    DecideResponse,
)

log = logging.getLogger("concierge.routers.approvals")

router = APIRouter()


async def _require_staff_token(
    x_staff_token: str | None = Header(None),
) -> str | None:
    """Simple token check for staff auth.

    In dev environments any non-empty token passes. In production a token
    comparison would be added — for now this gates the approval endpoints
    behind a shared secret.
    """
    settings = get_settings()
    if settings.ENV.lower() in {"dev", "development", "local", "test"}:
        if not x_staff_token:
            raise HTTPException(status_code=401, detail="Missing staff token")
        return x_staff_token
    # Production guard (placeholder — real auth comes in Week 3)
    if not x_staff_token or x_staff_token != settings.get("STAFF_TOKEN", None):
        raise HTTPException(status_code=401, detail="Invalid staff token")
    return x_staff_token


@router.get("/api/approvals", response_model=ApprovalQueueResponse)
async def list_approvals(
    db: AsyncSession = Depends(get_db),
    _: str | None = Depends(_require_staff_token),
) -> ApprovalQueueResponse:
    """List all pending Requests (needs_review + new), newest first."""
    result = await db.execute(
        select(Request)
        .where(Request.status.in_([RequestStatus.needs_review, RequestStatus.new]))
        .order_by(Request.created_at.desc())
    )
    requests = result.scalars().all()
    items = [
        ApprovalQueueItem(
            request_id=r.id,
            type=r.type.value,
            summary=r.summary,
            confidence=r.confidence,
            priority=r.priority.value,
            status=r.status.value,
            created_at=r.created_at,
            conversation_id=r.conversation_id,
        )
        for r in requests
    ]
    return ApprovalQueueResponse(requests=items, total=len(items))


@router.post("/api/approvals/decide", response_model=DecideResponse)
async def decide_approval(
    body: DecideRequest,
    db: AsyncSession = Depends(get_db),
    _: str | None = Depends(_require_staff_token),
) -> DecideResponse:
    """Approve or reject a pending Request.

    On approval: records the decision, triggers fulfilment (creates the
    Reservation row), then notifies. On rejection: records the decision
    with an optional note, then notifies.
    """
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