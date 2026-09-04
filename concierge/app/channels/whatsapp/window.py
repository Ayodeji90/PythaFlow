"""WhatsApp 24-hour session-window logic (Day 16).

WhatsApp only permits free-form text within 24h of the guest's last inbound
message; outside that window a pre-approved template is required. This answers
"is the window still open?" from the persisted message history, so both the
inbound reply and proactive sends (reminders/confirmations) can choose
text-vs-template correctly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Message
from ...models.enums import MessageRole


async def last_inbound_at(db: AsyncSession, conversation_id: UUID) -> datetime | None:
    """Timestamp of the most recent guest (inbound) message in the conversation."""
    return (
        await db.execute(
            select(Message.created_at)
            .where(
                Message.conversation_id == conversation_id,
                Message.role == MessageRole.guest,
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def session_window_open(db: AsyncSession, conversation_id: UUID, *, hours: int = 24) -> bool:
    """True if a free-form WhatsApp message may still be sent (the guest messaged
    within `hours`). False → a pre-approved template is required instead."""
    ts = await last_inbound_at(db, conversation_id)
    if ts is None:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return datetime.now(UTC) - ts <= timedelta(hours=hours)
