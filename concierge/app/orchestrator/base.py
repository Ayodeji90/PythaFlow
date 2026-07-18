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
