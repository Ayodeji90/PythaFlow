"""Fulfilment worker: dispatches approved Requests to handlers."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

from ..llm.service import LLMService
from ..models import Request
from ..models.enums import RequestStatus, RequestType
from ..services.redis import get_redis_client
from ..tools.registry import registry
from .service import transition

log = logging.getLogger("concierge.requests.fulfilment")


def _fulfilment_tool_name(req_type: RequestType) -> str:
    """Map a RequestType to its corresponding fulfilment tool name.

    reservation  -> create_reservation
    modification -> modify_reservation
    cancellation -> cancel_reservation
    """
    mapping = {
        RequestType.reservation: "create_reservation",
        RequestType.modification: "modify_reservation",
        RequestType.cancellation: "cancel_reservation",
    }
    tool_name = mapping.get(req_type)
    if not tool_name:
        raise ValueError(f"No fulfilment tool mapped for RequestType {req_type}")
    return tool_name


async def fulfil_request(
    db: Any,  # AsyncSession
    request_id: UUID,
    *,
    llm: LLMService | None = None,
) -> None:
    """Process an approved Request by dispatching to the correct fulfilment handler.

    Steps:
    1. Load the Request (must be approved).
    2. Transition to in_progress.
    3. Look up a fulfilment tool by Request.type (e.g. reservation -> create_reservation).
    4. Execute the tool (which writes the artefact, e.g. Reservation row).
    5. Transition to completed (or failed on error).
    6. All errors are caught and marked failed; the Request stays visible in the queue.

    Raises if the Request is not approved (prevents fulfilling needs_review).
    """
    result = await db.execute(
        select(Request).where(Request.id == request_id)
    )
    request = result.scalar_one()
    if request.status != RequestStatus.approved:
        raise ValueError(
            f"Request {request_id} must be approved before fulfilment, "
            f"got {request.status}"
        )

    # Mark in_progress so staff sees it's being worked on
    await transition(db, request_id, to=RequestStatus.in_progress)

    try:
        # Map Request.type to fulfilment tool name
        tool_name = _fulfilment_tool_name(request.type)
        tool = registry.get_fulfilment(tool_name)

        # Build tool context (similar to how tools_loop does it)
        from ..tools.base import ToolContext

        ctx = ToolContext(
            tenant_id=request.tenant_id,
            conversation_id=request.conversation_id,
            guest_id=request.guest_id,
        )

        # Day 18 fix: the payload is a JSONB dict, but the fulfilment tools
        # take a typed args object. Coerce through the tool's own args_model
        # (validates + ignores any extra keys) so an approved Request actually
        # fulfils — previously a dict was passed straight through and the tool
        # crashed on attribute access, silently marking the Request failed.
        args = tool.args_model.model_validate(request.payload)
        result_dict = await tool.run(args, ctx=ctx, db=db)

        # On success, mark completed
        await transition(db, request_id, to=RequestStatus.completed)

        # Day 12: dispatch a confirmation notification after successful fulfilment
        from ..notifications import NOTIF_MESSAGE_SENT, notify
        await notify(
            NOTIF_MESSAGE_SENT,
            tenant_id=request.tenant_id,
            request_id=request.id,
            payload={
                "subject": "confirmation",
                "type": request.type.value,
                "conversation_id": str(request.conversation_id),
            },
        )

        # Day 12: schedule a reminder for reservation-type requests.
        if request.type == RequestType.reservation and result_dict:
            try:
                from datetime import date, time

                from ..reminders import schedule_reminder

                payload = request.payload or {}
                res_date_str = payload.get("date") or result_dict.get("date")
                res_time_str = payload.get("time") or result_dict.get("time")
                res_id = result_dict.get("reservation_id") or str(request.id)
                if res_date_str and res_time_str:
                    res_date = (
                        date.fromisoformat(res_date_str)
                        if isinstance(res_date_str, str)
                        else res_date_str
                    )
                    res_time = (
                        time.fromisoformat(res_time_str)
                        if isinstance(res_time_str, str)
                        else res_time_str
                    )
                    booking_dt = datetime.combine(res_date, res_time, tzinfo=UTC)
                    redis = get_redis_client()
                    await schedule_reminder(
                        redis,
                        tenant_id=str(request.tenant_id),
                        reservation_id=str(res_id),
                        booking_dt=booking_dt,
                    )
            except Exception:  # noqa: BLE001 — reminder scheduling must not fail the booking
                log.exception("Failed to schedule reminder")

    except Exception as exc:  # noqa: BLE001 - we want to catch all errors
        # Log the failure (the tool's run method should already have logged via log_action?)
        # But we also want to mark the request failed
        await transition(
            db,
            request_id,
            to=RequestStatus.failed,
            resolution={"error": str(exc), "type": type(exc).__name__},
        )
        # Re-raise? The spec says the request stays visible in the queue —
        # failed is a terminal state, so we do not re-raise.