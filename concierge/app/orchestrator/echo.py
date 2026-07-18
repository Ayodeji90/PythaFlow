"""Day-3 placeholder orchestrator: proves the pipe end to end without any
intelligence. Superseded by `LLMOrchestrator` on Day 4, but kept — it's the
zero-dependency implementation the pipeline tests run against."""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas.message import InboundMessage, OutboundChunk
from .base import TurnContext


class EchoOrchestrator:
    name = "echo"

    async def handle(
        self,
        msg: InboundMessage,
        *,
        ctx: TurnContext,
        db: AsyncSession,
        redis: Any,
    ) -> AsyncIterator[OutboundChunk]:
        yield OutboundChunk(type="typing")
        yield OutboundChunk(
            type="message",
            content=f"You said: {msg.content}",
            metadata={"orchestrator": self.name},
        )
        yield OutboundChunk(type="done")
