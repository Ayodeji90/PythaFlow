"""Staff console: conversations API (Day 17).

- `GET /api/conversations?tenant=<slug>&channel=&status=&q=` — one list across
  every channel (web, WhatsApp, email…), newest first.
- `GET /api/conversations/{id}` — full ordered transcript + guest context +
  linked Requests.

Both are tenant-scoped (a cross-tenant id is a 404, never data) and gated by
the `X-Staff-Token` stopgap (real auth is Day 24). These endpoints are the
hard deliverable of Day 17 — the console page is just a client of them.
"""
from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import get_db, resolve_tenant_or_404
from ..models import Conversation, Guest, Message, Request
from ..models.enums import ChannelType, ConversationStatus, MessageRole
from ..schemas.console import (
    ConsoleMessage,
    ConversationDetail,
    ConversationListItem,
    ConversationListResponse,
    GuestContext,
    LinkedRequest,
)
from .console_auth import require_staff_token

log = logging.getLogger("concierge.routers.conversations")
router = APIRouter()

_LIST_CAP = 200  # conversations returned per list call (pilot-scale guard)


async def _last_message(db: AsyncSession, conv_id, tenant_id) -> Message | None:
    return (
        await db.execute(
            select(Message)
            .where(
                Message.conversation_id == conv_id,
                Message.tenant_id == tenant_id,
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


@router.get("/api/conversations", response_model=ConversationListResponse)
async def list_conversations(
    tenant: str = Query(...),
    channel: str | None = Query(None),
    status: str | None = Query(None),
    q: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_staff_token),
) -> ConversationListResponse:
    """All conversations for a tenant — every channel in one list.

    Filters: ``channel`` (webchat|whatsapp|email…), ``status``
    (active|human|closed), ``q`` (matches guest name / phone / message text).
    Sorted newest-first by the latest message.
    """
    t = await resolve_tenant_or_404(db, tenant)

    stmt = select(Conversation).where(Conversation.tenant_id == t.id)
    if channel:
        try:
            stmt = stmt.where(Conversation.channel_type == ChannelType(channel))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"bad channel: {channel}") from exc
    if status:
        try:
            stmt = stmt.where(Conversation.status == ConversationStatus(status))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"bad status: {status}") from exc
    if q:
        like = f"%{q}%"
        content_match = exists(
            select(Message.id).where(
                Message.conversation_id == Conversation.id,
                Message.tenant_id == t.id,
                Message.content.ilike(like),
            )
        )
        # Guest join is 1:1 and the content search is an EXISTS subquery, so
        # rows can't duplicate — no group_by needed.
        stmt = stmt.outerjoin(Guest, Conversation.guest_id == Guest.id).where(
            or_(
                Guest.display_name.ilike(like),
                Guest.phone.ilike(like),
                content_match,
            )
        )

    conversations = (
        (await db.execute(stmt.order_by(Conversation.updated_at.desc()).limit(_LIST_CAP)))
        .scalars()
        .all()
    )

    # Pilot-scale N+1 (last message + guest per row) is fine at this volume; a
    # batched DISTINCT ON query replaces it if the list ever gets large.
    items: list[ConversationListItem] = []
    for conv in conversations:
        last = await _last_message(db, conv.id, t.id)
        guest = await db.get(Guest, conv.guest_id) if conv.guest_id else None
        items.append(
            ConversationListItem(
                id=conv.id,
                channel_type=conv.channel_type.value,
                guest_name=guest.display_name if guest else None,
                guest_phone=guest.phone if guest else None,
                last_message_preview=(last.content[:120] if last else ""),
                status=conv.status.value,
                unread=1 if last and last.role == MessageRole.guest else 0,
                updated_at=last.created_at if last else conv.updated_at,
            )
        )
    items.sort(key=lambda i: (i.updated_at is not None, i.updated_at), reverse=True)
    return ConversationListResponse(conversations=items, total=len(items))


@router.get("/api/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: UUID,
    tenant: str = Query(...),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_staff_token),
) -> ConversationDetail:
    """Full transcript + guest context + linked Requests for one conversation.

    Tenant-scoped: a conversation that isn't this tenant's is a 404.
    """
    t = await resolve_tenant_or_404(db, tenant)
    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.tenant_id != t.id:
        raise HTTPException(status_code=404, detail="conversation not found")

    messages = (
        (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == conv.id)
                .order_by(Message.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    requests = (
        (
            await db.execute(
                select(Request)
                .where(Request.conversation_id == conv.id)
                .order_by(Request.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    guest = await db.get(Guest, conv.guest_id) if conv.guest_id else None

    return ConversationDetail(
        id=conv.id,
        channel_type=conv.channel_type.value,
        status=conv.status.value,
        external_thread_id=conv.external_thread_id,
        guest=(
            GuestContext(
                id=guest.id,
                display_name=guest.display_name,
                phone=guest.phone,
                preferences=guest.preferences or {},
            )
            if guest
            else None
        ),
        messages=[
            ConsoleMessage(
                id=m.id,
                role=m.role.value,
                content=m.content,
                content_type=m.content_type,
                created_at=m.created_at,
                delivery_ticks=m.meta.get("delivery") or {},
            )
            for m in messages
        ],
        requests=[
            LinkedRequest(
                id=r.id,
                type=r.type.value,
                status=r.status.value,
                priority=r.priority.value,
                summary=r.summary,
                confidence=r.confidence,
                created_at=r.created_at,
            )
            for r in requests
        ],
        updated_at=messages[-1].created_at if messages else conv.updated_at,
    )
