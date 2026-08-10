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
from .prompt import build_system_prompt
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
                yield OutboundChunk(
                    type="message",
                    content="I've sent this request to our team for review — "
                    "they'll confirm your booking shortly!",
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
            if not self._skip_extractor and get_settings().REQUEST_EXTRACTOR_ENABLED:
                asyncio.create_task(
                    _run_extractor(
                        llm=self._llm,
                        ctx=ctx,
                        msg=msg,
                        draft_already_created=draft_detected,
                    )
                )


async def _run_extractor(
    *,
    llm: LLMService,
    ctx: TurnContext,
    msg: InboundMessage,
    draft_already_created: bool,
) -> None:
    """Post-turn: classify the guest's intent into a Request.

    Runs fire-and-forget after the turn streams, so it never blocks the reply.
    If a draft tool already created a Request, skip extraction.
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
        try:
            await extract_db.commit()
        except Exception:  # noqa: BLE001 — background task must not crash
            log.exception("failed to persist extracted request")
            return

    await notify(
        NOTIF_REQUEST_CREATED,
        tenant_id=ctx.tenant.id,
        request_id=request.id,
        payload={"summary": request.summary, "type": request.type.value},
    )

    # Day 19: escalate when the rules fire (complaint, low confidence, VIP,
    # explicit ask) — flags the conversation (AI stands down) and alerts the
    # tenant's configured channels. Fresh session + fresh rows: this task's
    # request session is closed, and detached ORM objects don't flush reliably.
    try:
        from ..models import Conversation, Guest
        from ..models import Request as RequestModel
        from ..models import Tenant as TenantModel
        from .escalation import maybe_escalate

        async with SessionLocal() as esc_db:
            tenant = await esc_db.get(TenantModel, ctx.tenant.id)
            conv = await esc_db.get(Conversation, ctx.conversation.id)
            guest = await esc_db.get(Guest, conv.guest_id) if conv and conv.guest_id else None
            if tenant is not None and conv is not None:
                fresh_request = await esc_db.get(RequestModel, request.id)
                await maybe_escalate(
                    esc_db,
                    tenant=tenant,
                    conversation=conv,
                    guest=guest,
                    request=fresh_request,
                    message=msg.content,
                )
    except Exception:  # noqa: BLE001 — a failed escalation check must not crash the task
        log.exception("escalation check failed for conversation %s", ctx.conversation.id)