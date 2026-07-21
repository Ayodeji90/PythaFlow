"""The LLM orchestrator — the concierge's brain, as of Day 4.

Builds the persona from the tenant, loads history from Postgres, and streams the
reply token-by-token. It persists nothing: the shared pipeline
(`channels/base.py`) concatenates the `token` chunks and writes the assistant
turn. Grounding (Day 5) and guardrails (Day 6) slot in around this.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..knowledge.retrieve import format_context, retrieve
from ..llm.embeddings import EmbeddingService
from ..llm.factory import build_llm_service
from ..llm.service import LLMService
from ..models.enums import ConversationStatus
from ..schemas.message import InboundMessage, OutboundChunk
from ..services.locks import conversation_turn_lock
from .base import TurnContext
from .guardrails import GuardrailAction, check_inbound
from .prompt import build_system_prompt
from .state import load_history

log = logging.getLogger("concierge.orchestrator")


class LLMOrchestrator:
    name = "llm"

    def __init__(
        self,
        llm: LLMService | None = None,
        *,
        tier: str | None = None,
        embedder: EmbeddingService | None = None,
    ) -> None:
        # Injectable for tests (fake provider/embedder); built from settings otherwise.
        self._llm = llm or build_llm_service()
        self._tier = tier or get_settings().CHAT_TIER
        self._embedder = embedder  # lazily built inside retrieve() if None

    async def handle(
        self,
        msg: InboundMessage,
        *,
        ctx: TurnContext,
        db: AsyncSession,
        redis: Any,
    ) -> AsyncIterator[OutboundChunk]:
        # Serialise turns within a conversation so a double-send can't interleave
        # two replies. Waits its turn rather than dropping the message.
        async with conversation_turn_lock(redis, ctx.conversation.id) as acquired:
            if not acquired:
                yield OutboundChunk(
                    type="error",
                    content="Still finishing the previous reply — please resend in a moment.",
                )
                return

            # Guardrails (Day 6): rules are instant; the LLM moderator only runs on
            # borderline input. Refuse/Escalate short-circuit before we ever ask the
            # LLM to answer.
            guard = await check_inbound(msg.content, llm=self._llm, settings=get_settings())
            if guard.action is GuardrailAction.refuse:
                yield OutboundChunk(
                    type="message",
                    content=guard.message,
                    metadata={"guardrail": "refuse", "reason": guard.reason},
                )
                yield OutboundChunk(type="done", metadata={"guardrail": "refuse"})
                return
            if guard.action is GuardrailAction.escalate:
                ctx.conversation.status = ConversationStatus.human
                await db.commit()
                yield OutboundChunk(
                    type="action", content="escalated", metadata={"reason": guard.reason}
                )
                yield OutboundChunk(
                    type="message",
                    content=guard.message,
                    metadata={"guardrail": "escalate"},
                )
                yield OutboundChunk(type="done", metadata={"guardrail": "escalate"})
                return

            yield OutboundChunk(type="typing")

            # Retrieve venue facts for THIS question. If nothing clears the
            # similarity floor, `hits` is empty → the prompt tells the model to
            # say it'll check with the team rather than invent an answer.
            context = None
            try:
                hits = await retrieve(
                    db, tenant_id=ctx.tenant.id, query=msg.content, embedder=self._embedder
                )
                if hits:
                    context = format_context(hits)
            except Exception:  # noqa: BLE001 - retrieval failure shouldn't kill the turn
                log.exception("retrieval failed; answering ungrounded")

            system = build_system_prompt(ctx.tenant, context=context)
            history = await load_history(db, ctx.conversation.id)

            streamed = False
            try:
                async for fragment in self._llm.stream(history, tier=self._tier, system=system):
                    if fragment:
                        streamed = True
                        yield OutboundChunk(type="token", content=fragment)
            except Exception as exc:  # noqa: BLE001 - surface on the wire, don't crash the socket
                log.exception("LLM stream failed")
                yield OutboundChunk(
                    type="error",
                    content=f"{type(exc).__name__}: {exc}",
                    metadata={"stage": "llm"},
                )
                return

            if not streamed:
                yield OutboundChunk(
                    type="message",
                    content="Sorry — I didn't catch that. Could you rephrase?",
                )
            yield OutboundChunk(
                type="done",
                metadata={
                    "model": self._llm.model_for(self._tier),
                    "grounded": context is not None,
                },
            )
