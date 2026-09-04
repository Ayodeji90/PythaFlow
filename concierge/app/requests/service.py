"""Request service: open & transition helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Request
from ..models.enums import RequestPriority, RequestStatus, RequestType


async def open_request(
    db: AsyncSession,
    *,
    ctx: dict[str, Any],
    type: RequestType,
    payload: dict[str, Any],
    summary: str,
    confidence: float | None,
    priority: RequestPriority = RequestPriority.normal,
) -> Request:
    """Create or deduplicate a Request by tenant + idempotency key in payload.

    If an open (new|needs_review) Request exists with the same tenant and the
    idempotency key in its payload, return it. Otherwise insert a new Request.
    """
    idempotency_key = payload.get("idempotency_key")
    stmt = select(Request).where(
        Request.tenant_id == ctx["tenant_id"],
        Request.type == type,
        Request.status.in_([RequestStatus.new, RequestStatus.needs_review]),
    )
    if idempotency_key:
        stmt = stmt.where(Request.payload["idempotency_key"].astext == idempotency_key)

    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    request = Request(
        tenant_id=ctx["tenant_id"],
        conversation_id=ctx.get("conversation_id"),
        guest_id=ctx.get("guest_id"),
        type=type,
        status=RequestStatus.needs_review,
        priority=priority,
        summary=summary,
        payload=payload,
        confidence=confidence,
    )
    db.add(request)
    await db.flush()
    return request


async def transition(
    db: AsyncSession,
    request_id: UUID,
    *,
    to: RequestStatus,
    user_id: UUID | None = None,
    resolution: dict[str, Any] | None = None,
) -> Request:
    """Transition a Request to a new status, recording who decided and why.

    Legal transitions:
        new|needs_review -> approved|rejected
        approved -> in_progress -> completed|failed
    Anything else raises ValueError.
    """
    result = await db.execute(select(Request).where(Request.id == request_id))
    request = result.scalar_one()
    current = request.status

    allowed = False
    if current in (RequestStatus.new, RequestStatus.needs_review):
        if to in (RequestStatus.approved, RequestStatus.rejected):
            allowed = True
    elif current == RequestStatus.approved:
        if to == RequestStatus.in_progress:
            allowed = True
    elif current == RequestStatus.in_progress:
        if to in (RequestStatus.completed, RequestStatus.failed):
            allowed = True

    if not allowed:
        raise ValueError(
            f"Illegal Request transition: {current.value} -> {to.value} (request_id={request_id})"
        )

    # Enforce confidence & priority gates for auto-approve
    settings = get_settings()
    if to == RequestStatus.approved and request.priority == RequestPriority.high and not user_id:
        raise ValueError("High-priority requests require explicit staff approval")
    if (
        to == RequestStatus.approved
        and request.confidence is not None
        and request.confidence < settings.REQUEST_REVIEW_CONFIDENCE
        and not user_id
    ):
        raise ValueError(
            f"Low-confidence request (confidence={request.confidence}) "
            f"requires explicit staff approval"
        )

    request.status = to
    if to in (RequestStatus.approved, RequestStatus.rejected):
        request.decided_at = datetime.now(UTC)
    if user_id is not None:
        request.decided_by = user_id
    if resolution is not None:
        request.resolution = resolution

    await db.flush()
    return request
