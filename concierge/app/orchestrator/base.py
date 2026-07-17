"""The orchestrator contract.

Routers depend on this Protocol, never on a concrete implementation — so Day 4
swaps `EchoOrchestrator` for the LLM one without touching a single caller.

Note the signature is streaming (`AsyncIterator`) from day one even though the
echo has nothing to stream: Day 4's token streaming then needs no interface
change. `redis` is threaded through unused for the same reason (Day 4 hot state).

`handle` is declared as a plain `def` returning an `AsyncIterator` because an
async-generator function returns its iterator immediately (no await).
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas.message import InboundMessage, OutboundChunk


class Orchestrator(Protocol):
    name: str

    def handle(
        self,
        msg: InboundMessage,
        *,
        db: AsyncSession,
        redis: Any,
    ) -> AsyncIterator[OutboundChunk]: ...
