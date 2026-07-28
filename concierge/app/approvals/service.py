"""Approval service: records human decisions on Requests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Approval, Request
from ..models.enums import ApprovalStatus, RequestStatus


async def decide(
    db: AsyncSession,
    request_id: UUID,
    *,
    decision: str,  # "approved" or "rejected"
    user_id: UUID | None = None,
    note: str | None = None,
) -> Approval:
    """Record an approval or rejection decision on a Request.

    Steps:
    1. Load the Request.
    2. Validate the decision is allowed (see transition rules in Request service).
    3. Create an Approval row (request_id, decided_by, decided_at).
    4. Transition the Request to the new status (approved or rejected).
    5. Return the Approval object.

    The request must be in new|needs_review state.
    """
    from ..requests.service import transition  # avoid circular import at module level

    result = await db.execute(select(Request).where(Request.id == request_id))
    request = result.scalar_one()
    if request.status not in (RequestStatus.new, RequestStatus.needs_review):
        raise ValueError(
            f"Request {request_id} is not pending decision (status={request.status})"
        )

    # Map decision string to RequestStatus
    if decision == "approved":
        new_status = RequestStatus.approved
    elif decision == "rejected":
        new_status = RequestStatus.rejected
    else:
        raise ValueError(f"Decision must be 'approved' or 'rejected', got {decision}")

    # Create the Approval record
    approval = Approval(
        tenant_id=request.tenant_id,
        request_id=request.id,
        status=(
            ApprovalStatus.approved
            if decision == "approved"
            else ApprovalStatus.rejected
        ),
        decided_by=user_id,
        decided_at=datetime.now(UTC),
    )
    db.add(approval)
    await db.flush()

    # If rejected, we may want to store a note in the request's resolution field
    resolution_dict = None
    if decision == "rejected" and note is not None:
        resolution_dict = {"note": note}

    # Transition the Request
    await transition(
        db,
        request_id,
        to=new_status,
        user_id=user_id,
        resolution=resolution_dict,
    )

    return approval