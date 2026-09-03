"""Staff console • conversation endpoints (Day 17 W3-D17-2/3).

- GET  /api/conversations             — list, tenant-scoped, optional filters
- GET  /api/conversations/{id}        — full transcript + linked Request id

Cross-tenant access always 404 (never 403 — never even hint the row exists).
Every route requires the console stopgap token (real auth lands Day 24).
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import get_db
from ..deps_console import (
    require_console_token,
    require_tenant_via_token_or_slug,
)
from ..models import Conversation, Guest, Message, Request, Tenant
from ..models.enums import ChannelType, RequestStatus
from ..schemas.conversation import (
    ConversationDetailResponse,
    ConversationListItem,
    ConversationListResponse,
    TranscriptMessage,
)

router = APIRouter(prefix="/api/conversations")


def _channel_label(conv: Conversation) -> str:
    try:
        return conv.channel_type.value
    except AttributeError:
        return str(conv.channel_type)


def _status_label(conv: Conversation) -> str:
    try:
        return conv.status.value
    except AttributeError:
        return str(conv.status)


async def _preview_for(db: AsyncSession, conv_id: UUID) -> tuple[str, "datetime | None"]:
    """Return (preview_text, created_at) for the most recent message in the conv."""
    row = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conv_id)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if row is None:
        return ("", None)
    text = row.content
    if isinstance(text, str) and len(text) > 140:
        text = text[:137] + "..."
    return (text or "", row.created_at)


async def _guest_for(db: AsyncSession, conv: Conversation) -> tuple[str | None, str | None]:
    g = await db.get(Guest, conv.guest_id) if conv.guest_id else None
    if g is None:
        return (None, None)
    return (g.display_name, g.phone)


async def _has_pending_request(db: AsyncSession, tenant_id: UUID, conv_id: UUID) -> bool:
    n = (
        await db.execute(
            select(Request.id)
            .where(
                Request.tenant_id == tenant_id,
                Request.conversation_id == conv_id,
                Request.status.in_(
                    [RequestStatus.new, RequestStatus.needs_review, RequestStatus.approved]
                ),
            )
            .limit(1)
        )
    ).first()
    return n is not None


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    token: Annotated[str, Depends(require_console_token)],
    tenant: Annotated[Tenant, Depends(require_tenant_via_token_or_slug)],
    db: Annotated[AsyncSession, Depends(get_db)],
    channel: ChannelType | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, description="substring search across message text"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ConversationListResponse:
    """All conversations for the authenticated tenant, newest activity first."""
    stmt = select(Conversation).where(Conversation.tenant_id == tenant.id)
    if channel is not None:
        stmt = stmt.where(Conversation.channel_type == channel)
    if status_filter:
        # Accepts the enum value or a friendly alias; bare pass-through for now.
        stmt = stmt.where(Conversation.status == status_filter)
    stmt = stmt.order_by(Conversation.updated_at.desc()).limit(limit).offset(offset)

    convs = (await db.execute(stmt)).scalars().all()

    items: list[ConversationListItem] = []
    for conv in convs:
        name, phone = await _guest_for(db, conv)
        preview, last_at = await _preview_for(db, conv.id)
        if q and q.lower() not in (preview or "").lower():
            # Cheap filter; a real search would be a JOIN on messages + ts_rank,
            # but for a console list scale (<1k rows/tenant) this is fine.
            continue
        items.append(
            ConversationListItem(
                id=conv.id,
                channel_type=_channel_label(conv),
                external_thread_id=conv.external_thread_id,
                guest_name=name,
                guest_phone=phone,
                last_message_preview=preview,
                last_message_at=last_at or conv.updated_at,
                status=_status_label(conv),
                has_pending_request=await _has_pending_request(db, tenant.id, conv.id),
            )
        )
    return ConversationListResponse(total=len(items), conversations=items)


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: UUID,
    token: Annotated[str, Depends(require_console_token)],
    tenant: Annotated[Tenant, Depends(require_tenant_via_token_or_slug)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConversationDetailResponse:
    """Transcript + guest + linked-request id. Cross-tenant returns 404."""
    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.tenant_id != tenant.id:
        # Same response shape either way: don't leak the existence of another tenant's row.
        raise HTTPException(status_code=404, detail="conversation not found")

    msgs = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at)
        )
    ).scalars().all()

    name, phone = await _guest_for(db, conv)
    linked = (
        await db.execute(
            select(Request.id)
            .where(
                Request.tenant_id == tenant.id,
                Request.conversation_id == conv.id,
            )
            .order_by(Request.created_at.desc())
            .limit(1)
        )
    ).scalars().first()

    return ConversationDetailResponse(
        id=conv.id,
        channel_type=_channel_label(conv),
        external_thread_id=conv.external_thread_id,
        guest_name=name,
        guest_phone=phone,
        status=_status_label(conv),
        created_at=conv.created_at,
        messages=[
            TranscriptMessage(
                id=m.id,
                role=str(m.role.value if hasattr(m.role, "value") else m.role),
                content=m.content,
                content_type=m.content_type,
                created_at=m.created_at,
                meta=m.meta,
            )
            for m in msgs
        ],
        linked_request_id=linked,
    )
