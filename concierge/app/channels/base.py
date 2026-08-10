"""Channel contract + the shared inbound pipeline.

`handle_inbound()` is deliberately channel-agnostic: resolve tenant → resolve or
create the conversation → persist the guest turn → run the orchestrator → persist
the assistant turn, streaming chunks through as they come. Adding a channel
(WhatsApp on Day 15) means writing a `to_inbound()` — not touching any of this.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Channel, Conversation, Message, Tenant
from ..models.enums import ChannelType, ConversationStatus, MessageRole
from ..orchestrator.base import Orchestrator, TurnContext
from ..schemas.message import InboundMessage, OutboundChunk


class TenantNotFound(LookupError):
    """Raised when an inbound message names a tenant slug we don't have."""


class ChannelAdapter(Protocol):
    """What a channel must provide. Rendering is channel-specific too, but for
    web chat the JSON chunk *is* the wire format, so there's nothing to render."""

    channel: ChannelType

    def to_inbound(self, **kwargs: Any) -> InboundMessage: ...


async def _resolve_tenant(db: AsyncSession, slug: str) -> Tenant:
    tenant = (
        await db.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if tenant is None:
        raise TenantNotFound(f"unknown tenant '{slug}'")
    return tenant


async def _resolve_conversation(
    db: AsyncSession, tenant: Tenant, msg: InboundMessage
) -> Conversation:
    """Find this thread, or start one. Uses the (tenant_id, external_thread_id)
    index added on Day 2."""
    conv = (
        await db.execute(
            select(Conversation).where(
                Conversation.tenant_id == tenant.id,
                Conversation.external_thread_id == msg.conversation_ref,
            )
        )
    ).scalar_one_or_none()
    if conv is not None:
        return conv

    # Link the Channel row for this tenant+type when one is configured.
    channel = (
        await db.execute(
            select(Channel).where(
                Channel.tenant_id == tenant.id,
                Channel.type == msg.channel,
                Channel.active.is_(True),
            )
        )
    ).scalars().first()

    conv = Conversation(
        tenant_id=tenant.id,
        channel_id=channel.id if channel else None,
        channel_type=msg.channel,
        external_thread_id=msg.conversation_ref,
        language=msg.locale,
        # guest_id stays NULL — web chat is anonymous. Guest identity is Day 11.
    )
    db.add(conv)
    await db.flush()
    return conv


async def handle_inbound(
    msg: InboundMessage,
    *,
    db: AsyncSession,
    redis: Any,
    orchestrator: Orchestrator,
) -> AsyncIterator[OutboundChunk]:
    tenant = await _resolve_tenant(db, msg.tenant_slug)
    conv = await _resolve_conversation(db, tenant, msg)

    # Day 11: resolve/create a Guest record for this conversation.
    guest_name = msg.sender.name if msg.sender else None
    from ..guest_memory import (
        build_guest_context,
        extract_preferences,
        resolve_guest,
        update_guest_preferences,
    )

    guest = await resolve_guest(db, tenant.id, conv.id, display_name=guest_name)

    # Extract and store any preferences from this turn.
    prefs = extract_preferences(msg.content)
    await update_guest_preferences(db, guest.id, prefs)

    # Build guest context for the orchestrator.
    guest_context = await build_guest_context(db, tenant.id, conv.id)

    # Persist the guest turn before thinking, so it survives an orchestrator failure.
    db.add(
        Message(
            tenant_id=tenant.id,
            conversation_id=conv.id,
            role=MessageRole.guest,
            content=msg.content,
            content_type=msg.content_type,
            meta={"sender": msg.sender.model_dump(exclude_none=True), **msg.metadata},
        )
    )
    await db.commit()

    # Day 18: while staff have taken over (or the Day-6 guardrail escalated),
    # the AI stands down on EVERY channel — checked here, before the
    # orchestrator. The guest turn is already persisted, so staff see it.
    if conv.status == ConversationStatus.human:
        yield OutboundChunk(
            type="message",
            content="A staff member is handling this conversation — the concierge is paused.",
            metadata={"paused": True, "status": "human"},
        )
        return

    ctx = TurnContext(
        tenant=tenant,
        conversation=conv,
        guest_context=guest_context,
        state=conv.state,
    )
    parts: list[str] = []
    try:
        async for chunk in orchestrator.handle(msg, ctx=ctx, db=db, redis=redis):
            if chunk.content and chunk.type in ("token", "message"):
                parts.append(chunk.content)
            yield chunk
    except Exception as exc:  # noqa: BLE001 - surface failures on the wire
        yield OutboundChunk(type="error", content=f"{type(exc).__name__}: {exc}")
        return

    reply = "".join(parts)
    if reply:
        db.add(
            Message(
                tenant_id=tenant.id,
                conversation_id=conv.id,
                role=MessageRole.assistant,
                content=reply,
                meta={"orchestrator": getattr(orchestrator, "name", "unknown")},
            )
        )
        await db.commit()
