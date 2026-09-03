"""The LLM orchestrator — the concierge's brain, as of Day 10.

Builds the persona from the tenant, loads history from Postgres, and streams the
reply token-by-token. It persists nothing: the shared pipeline
(`channels/base.py`) concatenates the `token` chunks and writes the assistant
turn. Grounding (Day 5) and guardrails (Day 6) slot in around this.

Day 10 addition: post-tool-loop draft awareness + fire-and-forget request
extractor for unhandled intents.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..knowledge.retrieve import format_context, retrieve
from ..llm.embeddings import EmbeddingService
from ..llm.factory import build_llm_service
from ..llm.service import LLMService
from ..models.enums import ConversationStatus, RequestType
from ..schemas.message import InboundMessage, OutboundChunk
from ..services.locks import conversation_turn_lock
from .base import TurnContext
from .guardrails import GuardrailAction, check_inbound
from .prompt import build_post_draft_message, build_system_prompt
from .state import load_history
from .tools_loop import run_tool_loop

log = logging.getLogger("concierge.orchestrator")


class LLMOrchestrator:
    name = "llm"

    def __init__(
        self,
        llm: LLMService | None = None,
        *,
        tier: str | None = None,
        embedder: EmbeddingService | None = None,
        _skip_extractor: bool = False,
    ) -> None:
        # Injectable for tests (fake provider/embedder); built from settings otherwise.
        self._llm = llm or build_llm_service()
        self._tier = tier or get_settings().CHAT_TIER
        self._embedder = embedder  # lazily built inside retrieve() if None
        self._skip_extractor = _skip_extractor

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

            system = build_system_prompt(
                ctx.tenant,
                context=context,
                guest_context=ctx.guest_context,
                state=ctx.state,
                channel=msg.channel.value if msg.channel else None,
            )
            history = await load_history(db, ctx.conversation.id)

            # Tool-calling loop (Phase 1.3): runs up to TOOLS_MAX_STEPS turns,
            # executing any tool calls the LLM makes and yielding the final
            # natural-language answer. If no tools are registered this behaves
            # exactly like a plain LLM.generate call.
            streamed = False
            draft_detected = False  # Day 10: track whether a draft tool was called
            try:
                async for chunk in run_tool_loop(
                    self._llm,
                    history,
                    system=system,
                    ctx=ctx,
                    db=db,
                    tier=self._tier,
                ):
                    if chunk.type == "action" and chunk.content == "draft_reservation":
                        draft_detected = True
                    if chunk.type == "token" and chunk.content:
                        streamed = True
                    yield chunk
            except Exception as exc:  # noqa: BLE001 - surface on the wire, don't crash the socket
                log.exception("Tool loop failed")
                yield OutboundChunk(
                    type="error",
                    content=f"{type(exc).__name__}: {exc}",
                    metadata={"stage": "tool_loop"},
                )
                return

            if not streamed:
                yield OutboundChunk(
                    type="message",
                    content="Sorry — I didn't catch that. Could you rephrase?",
                )

            # Day 10: if a draft_reservation was created, tell the guest it's
            # pending staff review.
            if draft_detected:
                # Day 12: save slot state into Conversation.state so subsequent
                # turns can reference in-progress booking details.
                if ctx.state is not None:
                    ctx.state["intent"] = "reservation"
                # D3: brand-voiced post-draft message (replaces hardcoded text)
                post_draft_msg = build_post_draft_message(
                    ctx.tenant, request_type="reservation"
                )
                yield OutboundChunk(
                    type="message",
                    content=post_draft_msg,
                    metadata={"stage": "approval"},
                )

            yield OutboundChunk(
                type="done",
                metadata={
                    "model": self._llm.model_for(self._tier),
                    "grounded": context is not None,
                    "draft_created": draft_detected,
                },
            )

            # Day 10: fire-and-forget request extractor for unhandled intents.
            # E1 fix: retry with backoff + dead-letter on permanent failure.
            if not self._skip_extractor and get_settings().REQUEST_EXTRACTOR_ENABLED:
                asyncio.create_task(
                    _run_extractor_with_retry(
                        llm=self._llm,
                        ctx=ctx,
                        msg=msg,
                        draft_already_created=draft_detected,
                    )
                )


# E1: retry config for the request extractor
_EXTRACTOR_MAX_RETRIES = 3
_EXTRACTOR_BASE_DELAY = 1.0  # seconds; doubles each attempt


async def _run_extractor_with_retry(
    *,
    llm: LLMService,
    ctx: TurnContext,
    msg: InboundMessage,
    draft_already_created: bool,
) -> None:
    """Post-turn extractor with retry + dead-letter.

    Retries up to _EXTRACTOR_MAX_RETRIES times with exponential backoff.
    On permanent failure, logs a dead-letter event so the staff console can
    surface it — the guest's intent is never silently lost.
    """
    if draft_already_created:
        return

    last_exc: Exception | None = None
    for attempt in range(_EXTRACTOR_MAX_RETRIES):
        try:
            await _run_extractor(
                llm=llm, ctx=ctx, msg=msg, draft_already_created=draft_already_created
            )
            return  # success
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            delay = _EXTRACTOR_BASE_DELAY * (2 ** attempt)
            log.warning(
                "Extractor attempt %d/%d failed: %s — retrying in %.1fs",
                attempt + 1,
                _EXTRACTOR_MAX_RETRIES,
                exc,
                delay,
            )
            await asyncio.sleep(delay)

    # All retries exhausted — dead-letter: log + notify so staff sees it
    log.error(
        "Extractor permanently failed after %d attempts for conversation=%s: %s",
        _EXTRACTOR_MAX_RETRIES,
        ctx.conversation.id,
        last_exc,
    )
    try:
        from ..notifications import NOTIF_REQUEST_CREATED, notify

        await notify(
            NOTIF_REQUEST_CREATED,
            tenant_id=ctx.tenant.id,
            request_id=ctx.conversation.id,  # use conv id as stable key
            payload={
                "summary": f"[EXTRACTION FAILED] Guest said: {msg.content[:120]}",
                "type": "extraction_failed",
                "error": str(last_exc),
                "guest_message": msg.content,
            },
        )
    except Exception:  # noqa: BLE001
        log.exception("dead-letter notification also failed")


async def _run_extractor(
    *,
    llm: LLMService,
    ctx: TurnContext,
    msg: InboundMessage,
    draft_already_created: bool,
) -> None:
    """Single attempt: classify the guest's intent into a Request.

    Raises on failure so the retry wrapper can catch it.
    """
    if draft_already_created:
        return

    from ..db import SessionLocal
    from ..notifications import NOTIF_REQUEST_CREATED, notify
    from ..requests.extractor import extract_request
    from ..requests.service import open_request

    turns = [
        {"role": "guest", "content": msg.content},
    ]

    extracted = await extract_request(
        llm,
        tenant_id=ctx.tenant.id,
        conversation_id=ctx.conversation.id,
        guest_id=None,
        turns=turns,
    )
    if extracted is None or extracted.get("type") == RequestType.none:
        return

    # Use a fresh session so we don't interfere with the request's transaction.
    async with SessionLocal() as extract_db:
        request = await open_request(
            extract_db,
            ctx={
                "tenant_id": ctx.tenant.id,
                "conversation_id": ctx.conversation.id,
            },
            type=extracted["type"],
            payload=extracted["payload"],
            summary=extracted["summary"],
            confidence=extracted["confidence"],
            priority=extracted["priority"],
        )
        await extract_db.commit()

    await notify(
        NOTIF_REQUEST_CREATED,
        tenant_id=ctx.tenant.id,
        request_id=request.id,
        payload={"summary": request.summary, "type": request.type.value},
    )