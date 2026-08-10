"""Console audit trail (Day 18).

Every staff mutation — approve, reject, edit, takeover, resume, staff send —
writes an `Action` row (the Day-8 audit model) via the existing
`tools.logging.log_action` helper, so the who/what/when of every console action
is visible without touching the append-only `Approval` table (a reversal is a
new row, never an overwrite).

Actor is a stopgap: `X-Staff-Token` is a shared secret with no per-user
identity until Day 24's real auth, so we record a masked token prefix. Honest,
loudly documented, and better than nothing.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from .models import Action
from .models.enums import ActionStatus
from .tools.logging import log_action


def actor_from_token(token: str | None) -> str:
    """Masked pseudo-identity from the shared staff token (stopgap until Day 24)."""
    if not token:
        return "unknown"
    return f"staff:{token[:6]}…"


async def record_audit(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    conversation_id: UUID | None,
    action: str,
    actor: str,
    detail: dict | None = None,
) -> Action:
    """Write one console action to the audit trail."""
    return await log_action(
        db,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        type=f"console.{action}",
        input={"actor": actor},
        output=detail or {},
        status=ActionStatus.executed,
    )
