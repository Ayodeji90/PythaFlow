"""Conversation state.

Postgres is the **single source of truth** for history — it's an indexed read of a
handful of rows, and a cache here would risk the model "forgetting" the guest's
last message. Redis does something it's actually good at instead: a per-conversation
turn lock (see `app/services/locks.py`).
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..llm.base import LLMMessage
from ..models import Message
from ..models.enums import MessageRole

# How much history to carry. Trimmed oldest-first; when conversations outgrow
# this we summarise the overflow instead (see `_summarise_overflow`).
MAX_HISTORY_MESSAGES = 20

_ROLE_MAP = {
    MessageRole.guest: "user",
    MessageRole.assistant: "assistant",
    # A human took over — to the model that's still the venue speaking.
    MessageRole.staff: "assistant",
}


async def load_history(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    *,
    limit: int = MAX_HISTORY_MESSAGES,
) -> list[LLMMessage]:
    """Recent turns as LLM messages, oldest → newest.

    Note: the pipeline persists the guest's current turn *before* the orchestrator
    runs, so the returned list already ends with the message being answered.
    """
    rows = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    history: list[LLMMessage] = []
    for row in reversed(rows):  # back into chronological order
        role = _ROLE_MAP.get(row.role)
        if role is None or not row.content:
            continue  # system/tool rows aren't conversation turns
        history.append(LLMMessage(role=role, content=row.content))
    return history


def _summarise_overflow(_dropped: list[LLMMessage]) -> str | None:
    """Hook: once conversations run long, summarise what we trimmed and prepend it
    to the system prompt. Not needed yet at 20 turns."""
    return None
