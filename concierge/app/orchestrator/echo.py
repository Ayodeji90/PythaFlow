"""Day-3 placeholder orchestrator: proves the pipe end to end without any
intelligence. Replaced by the LLM orchestrator on Day 4."""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas.message import InboundMessage, OutboundChunk


class EchoOrchestrator:
    name = "echo"

    async def handle(
        self,
        msg: InboundMessage,
        *,
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
