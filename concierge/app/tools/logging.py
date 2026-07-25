"""Action-logging helper used by the tool loop.

Every tool invocation is recorded as an Action row so the staff dashboard can
review what the AI proposed, what was executed, and what failed."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ..models.action import Action
from ..models.enums import ActionStatus


async def log_action(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    conversation_id: UUID | None,
    type: str,
    input: dict,
    output: dict,
    status: ActionStatus = ActionStatus.executed,
) -> Action:
    """Persist a tool-invocation Action record."""
    action = Action(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        type=type,
        input=input,
        output=output,
        status=status,
    )
    db.add(action)
    await db.flush()
    return action