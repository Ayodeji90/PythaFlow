"""Human takeover (Day 18) — the human-in-the-loop promise, made physical.

- `POST /api/conversations/{id}/takeover?tenant=` — staff takes over: sets
  `Conversation.status=human`. From that moment the AI stands down on *every*
  channel (the guard lives in `channels/base.handle_inbound`, checked before
  the orchestrator). This is the same `status=human` state the Day-6 guardrail
  escalation sets — takeover is simply the manual trigger for it.
- `POST /api/conversations/{id}/staff-message` — staff reply **as the venue**:
  persisted as a `role=staff` Message and delivered over WhatsApp through the
  same outbound transport as the concierge (the ``notify()`` seam — the Week-2
  "transport swap, not rewrite").
- `POST /api/conversations/{id}/resume` — hands control back to the AI
  (`status=active`).

Every mutation is tenant-scoped (cross-tenant → 404) and written to the audit
trail. All gated by the `X-Staff-Token` stopgap (real auth is Day 24).
"""
from __future__ import annotations

import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import actor_from_token, record_audit
from ..deps import get_db, resolve_tenant_or_404
from ..models import Conversation, Message
from ..models.enums import ConversationStatus, MessageRole
from ..notifications import NOTIF_MESSAGE_SENT, notify
from .console_auth import require_staff_token

log = logging.getLogger("concierge.routers.takeover")
router = APIRouter()


class StaffMessageBody(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


async def _tenant_scoped_conversation(
    db: AsyncSession, conversation_id: UUID, tenant_slug: str
) -> Conversation:
    tenant = await resolve_tenant_or_404(db, tenant_slug)
    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="conversation not found")
    return conv


@router.post("/api/conversations/{conversation_id}/takeover")
async def takeover(
    conversation_id: UUID,
    tenant: str = Query(...),
    token: str = Depends(require_staff_token),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Staff takes over: AI stands down, staff can reply as the venue."""
    actor = actor_from_token(token)
    conv = await _tenant_scoped_conversation(db, conversation_id, tenant)
    if conv.status != ConversationStatus.human:
        conv.status = ConversationStatus.human
        await record_audit(
            db,
            tenant_id=conv.tenant_id,
            conversation_id=conv.id,
            action="takeover",
            actor=actor,
            detail={},
        )
        await db.commit()
        log.info("staff %s took over conversation %s", actor, conv.id)
    return {"status": "human", "conversation_id": str(conv.id)}


@router.post("/api/conversations/{conversation_id}/resume")
async def resume(
    conversation_id: UUID,
    tenant: str = Query(...),
    token: str = Depends(require_staff_token),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Hand control back to the AI."""
    conv = await _tenant_scoped_conversation(db, conversation_id, tenant)
    if conv.status != ConversationStatus.active:
        conv.status = ConversationStatus.active
        await record_audit(
            db,
            tenant_id=conv.tenant_id,
            conversation_id=conv.id,
            action="resume",
            actor=actor_from_token(token),
            detail={},
        )
        await db.commit()
        log.info("staff %s resumed AI on conversation %s", actor_from_token(token), conv.id)
    return {"status": "active", "conversation_id": str(conv.id)}


@router.post("/api/conversations/{conversation_id}/staff-message")
async def staff_message(
    conversation_id: UUID,
    body: StaffMessageBody,
    tenant: str = Query(...),
    token: str = Depends(require_staff_token),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Staff reply, sent as the venue through the same outbound transport.

    Only allowed while a takeover is active (status=human) — this is the guard
    that keeps staff and the AI from both replying. The row is persisted here
    (role=staff — visibly *not* the AI) and the WhatsApp transport delivers
    it, keyed by a fresh nonce so it can never be deduped against a
    notification.
    """
    actor = actor_from_token(token)
    conv = await _tenant_scoped_conversation(db, conversation_id, tenant)
    if conv.status != ConversationStatus.human:
        raise HTTPException(status_code=409, detail="take over first — the AI is still active")

    # Audit BEFORE the send so a slow BSP (retries) can never delay or skip it.
    nonce = str(uuid4())
    await record_audit(
        db,
        tenant_id=conv.tenant_id,
        conversation_id=conv.id,
        action="staff_send",
        actor=actor,
        detail={"content_preview": body.content[:80], "nonce": nonce},
    )
    db.add(
        Message(
            tenant_id=conv.tenant_id,
            conversation_id=conv.id,
            role=MessageRole.staff,
            content=body.content,
            meta={"channel": conv.channel_type.value, "sender": "staff"},
        )
    )
    await db.commit()

    # Deliver over WhatsApp via the notify() seam (same transport as the
    # concierge's own outbound). No-op for channels without a push transport.
    await notify(
        NOTIF_MESSAGE_SENT,
        tenant_id=conv.tenant_id,
        request_id=None,  # notify() requires the kwarg; this send has no Request
        payload={
            "message": body.content,
            "role": "staff",
            "nonce": nonce,
            "conversation_id": str(conv.id),
            "channel_type": conv.channel_type.value,
        },
    )
    return {"status": "sent", "conversation_id": str(conv.id), "role": "staff"}
