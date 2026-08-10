"""Escalation rules (Day 19) — the right things reach a human fast.

A small rule set, each trigger independent and reusing signals that already
exist in the system (no new state invented):

- ``low_confidence`` — ``Request.confidence < REQUEST_REVIEW_CONFIDENCE``
  (the extractor's own forced-review threshold).
- ``complaint``      — ``Request.type == complaint``.
- ``vip``            — ``Guest.preferences.vip`` is truthy.
- ``explicit_ask``   — the guest asked to speak to a human (mirrors the
  Day-6 guardrail pattern, so an ask that slipped through still escalates).

Applying an escalation: sets ``Conversation.status = human`` (the exact flag
the Day-6 guardrail escalation and the Day-18 takeover use — the AI stands
down via the Day-18 pipeline guard), bumps the Request priority to ``high``,
and fires ``NOTIF_ESCALATED`` to the tenant's configured channels. A
conversation already ``human`` doesn't re-notify (no alert spam) — it only
bumps the new Request's priority.

Per-tenant off-switch: ``Tenant.config["escalation"]["enabled"] is False``
disables all rules for that venue.
"""
from __future__ import annotations

import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings, get_settings
from ..models import Guest, Request, Tenant
from ..models.enums import ConversationStatus, RequestPriority, RequestType
from ..notifications import NOTIF_ESCALATED, notify

log = logging.getLogger("concierge.escalation")

# Mirrors guardrails._HUMAN_REQUEST so an explicit ask always escalates, even
# if the moderation path missed it.
_EXPLICIT_ASK = re.compile(
    r"\b(speak|talk|chat|connect)\b.{0,15}\b(to|with)\b.{0,15}"
    r"\b(a\s+)?(human|person|manager|someone|somebody|staff|representative|agent|owner)\b"
    r"|\bget me (a|the)\s+(human|manager|person|owner)\b",
    re.IGNORECASE,
)


def evaluate_reasons(
    *,
    request: Request | None,
    guest: Guest | None,
    message: str | None,
    settings: Settings,
) -> list[str]:
    """Which escalation rules fire for this turn? (pure, testable)"""
    reasons: list[str] = []
    if request is not None:
        if request.type == RequestType.complaint:
            reasons.append("complaint")
        if (
            request.confidence is not None
            and request.confidence < settings.REQUEST_REVIEW_CONFIDENCE
        ):
            reasons.append("low_confidence")
    if guest is not None and bool((guest.preferences or {}).get("vip")):
        reasons.append("vip")
    if _EXPLICIT_ASK.search(message or ""):
        reasons.append("explicit_ask")
    return reasons


async def maybe_escalate(
    db: AsyncSession,
    *,
    tenant: Tenant,
    conversation,
    guest: Guest | None,
    request: Request | None,
    message: str | None,
) -> list[str]:
    """Escalate when any rule fires. Returns the reasons ([] when none)."""
    esc_cfg = (tenant.config or {}).get("escalation", {})
    if esc_cfg.get("enabled") is False:
        return []

    reasons = evaluate_reasons(
        request=request, guest=guest, message=message, settings=get_settings()
    )
    if not reasons:
        return []

    transitioned = conversation.status != ConversationStatus.human
    if transitioned:
        conversation.status = ConversationStatus.human
    if request is not None and request.priority != RequestPriority.high:
        request.priority = RequestPriority.high
    await db.commit()

    if transitioned:
        log.info(
            "escalated conversation %s (%s)",
            conversation.id,
            ", ".join(reasons),
        )
        await notify(
            NOTIF_ESCALATED,
            tenant_id=tenant.id,
            request_id=request.id if request is not None else None,
            payload={
                "reason": reasons,
                "conversation_id": str(conversation.id),
                "request_id": str(request.id) if request is not None else None,
                "summary": request.summary if request is not None else None,
                "guest_name": guest.display_name if guest is not None else None,
            },
        )
    else:
        log.info(
            "conversation %s already escalated — bumped request priority only",
            conversation.id,
        )
    return reasons
