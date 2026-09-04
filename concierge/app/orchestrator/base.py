"""The orchestrator contract.

Routers depend on this Protocol, never on a concrete implementation — so swapping
`EchoOrchestrator` for `LLMOrchestrator` is a one-line change.

The signature is streaming (`AsyncIterator`) so token streaming needs no interface
change. `handle` is a plain `def` returning an `AsyncIterator` because an
async-generator function returns its iterator immediately (no await).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Conversation, Tenant
from ..schemas.message import InboundMessage, OutboundChunk


@dataclass
class TurnContext:
    """What the pipeline already resolved for this turn. Passed in so the
    orchestrator doesn't re-query the tenant/conversation on every message."""

    tenant: Tenant
    conversation: Conversation
    guest_context: str | None = None  # Day 11: known guest preferences snippet
    state: dict | None = None  # Day 12: Conversation.state JSONB (booking slots)

    def to_tool_context(self) -> Any:
        """Convert to the ToolContext expected by tools."""
        from ..tools.base import ToolContext

        return ToolContext(
            tenant_id=self.tenant.id,
            conversation_id=self.conversation.id,
            guest_id=None,
            channel_type=self.conversation.channel_type.value
            if self.conversation.channel_type
            else "webchat",
        )


class Orchestrator(Protocol):
    name: str

    def handle(
        self,
        msg: InboundMessage,
        *,
        ctx: TurnContext,
        db: AsyncSession,
        redis: Any,
    ) -> AsyncIterator[OutboundChunk]: ...
