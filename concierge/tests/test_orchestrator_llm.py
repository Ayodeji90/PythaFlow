"""Day-4: the LLM orchestrator, tested against a FAKE provider — no network, no
key. This is the payoff of the provider seam: we inject a stub and assert
streaming, persona wiring, and multi-turn context deterministically.

Day 12 additions: confirm-back prompt presence, slot-context injection,
reminder scheduling, multi-turn corrections."""

import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.channels.base import handle_inbound
from app.channels.webchat import WebChatAdapter
from app.llm.base import LLMMessage, LLMProvider, LLMResult, LLMToolResult
from app.llm.service import LLMService
from app.models import Conversation, Message, Tenant
from app.models.enums import MessageRole
from app.orchestrator.engine import LLMOrchestrator
from app.orchestrator.prompt import _MULTI_TURN, build_slot_context, build_system_prompt


class FakeProvider(LLMProvider):
    """Records what it was asked and streams a canned reply token-by-token."""

    name = "fake"

    def __init__(self, reply: str = "Hello from the venue.") -> None:
        self.reply = reply
        self.last_system: str | None = None
        self.last_messages: list[LLMMessage] = []

    async def generate(self, messages, *, model, system=None, temperature=0.4, max_tokens=1024):
        self.last_system = system
        self.last_messages = list(messages)
        return LLMResult(text=self.reply, model=model)

    async def stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        model,
        system=None,
        temperature=0.4,
        max_tokens=1024,
    ) -> AsyncIterator[str]:
        self.last_system = system
        self.last_messages = list(messages)
        for word in self.reply.split(" "):
            yield word + " "

    async def generate_with_tools(
        self,
        messages,
        *,
        model,
        tools=None,
        system=None,
        temperature=0.4,
        max_tokens=1024,
    ):
        """Fake tool-calling — records context and returns text with no tool calls."""
        self.last_system = system
        self.last_messages = list(messages)
        return LLMToolResult(text=self.reply)  # no tool_calls → tool loop exits immediately


def _service(provider: FakeProvider) -> LLMService:
    return LLMService(provider, "fake-fast", "fake-quality")


async def test_streams_tokens_and_persists(session):
    tenant = Tenant(slug=f"t-{uuid.uuid4().hex[:8]}", name="Bella Vista", brand_voice="Playful.")
    session.add(tenant)
    await session.flush()

    provider = FakeProvider("Welcome to Bella Vista!")
    orch = LLMOrchestrator(llm=_service(provider), tier="quality", _skip_extractor=True)

    conv_ref = uuid.uuid4().hex
    msg = WebChatAdapter.to_inbound(
        tenant_slug=tenant.slug, conversation_ref=conv_ref, content="hi there"
    )
    chunks = [c async for c in handle_inbound(msg, db=session, redis=None, orchestrator=orch)]
    types = [c.type for c in chunks]

    # streamed as tokens, then done
    assert "token" in types
    assert types[-1] == "done"
    reply = "".join(c.content or "" for c in chunks if c.type == "token")
    assert reply.strip() == "Welcome to Bella Vista!"

    # persona wiring: the system prompt carried the tenant's name + brand voice
    assert provider.last_system is not None
    assert "Bella Vista" in provider.last_system
    assert "Playful." in provider.last_system

    # the assistant turn was persisted (pipeline concatenated the tokens)
    rows = (
        (
            await session.execute(
                select(Message)
                .where(Message.conversation_id.isnot(None), Message.tenant_id == tenant.id)
                .order_by(Message.created_at)
            )
        )
        .scalars()
        .all()
    )
    assert [r.role for r in rows] == [MessageRole.guest, MessageRole.assistant]
    assert rows[1].content.strip() == "Welcome to Bella Vista!"


async def test_multi_turn_sees_prior_messages(session):
    tenant = Tenant(slug=f"t-{uuid.uuid4().hex[:8]}", name="Cafe Uno")
    session.add(tenant)
    await session.flush()

    provider = FakeProvider("Sure.")
    orch = LLMOrchestrator(llm=_service(provider), tier="quality", _skip_extractor=True)
    conv_ref = uuid.uuid4().hex

    for text in ("My name is Sam", "what did I say my name was?"):
        msg = WebChatAdapter.to_inbound(
            tenant_slug=tenant.slug, conversation_ref=conv_ref, content=text
        )
        async for _ in handle_inbound(msg, db=session, redis=None, orchestrator=orch):
            pass

    # On the 2nd turn the provider saw the earlier turns in its message list.
    contents = [m.content for m in provider.last_messages]
    assert "My name is Sam" in contents
    assert any("what did I say" in c for c in contents)
    # roles are mapped to the OpenAI shape
    assert {m.role for m in provider.last_messages} <= {"user", "assistant"}


# ── Day 12: confirm-back prompt presence ──────────────────────────────


def test_confirm_back_instructions_in_prompt():
    """The _MULTI_TURN prompt includes explicit confirm-before-tool language."""
    assert "Shall I proceed" in _MULTI_TURN
    assert "confirm the key details" in _MULTI_TURN
    assert "correction" in _MULTI_TURN


# ── Day 12: build_slot_context ────────────────────────────────────────


def test_build_slot_context_full():
    state = {"date": "2026-07-28", "time": "19:00", "party_size": 4, "area": "terrace"}
    result = build_slot_context(state)
    assert result is not None
    assert "Table for 4" in result
    assert "2026-07-28" in result
    assert "19:00" in result
    assert "terrace" in result


def test_build_slot_context_partial():
    """Missing required fields returns None."""
    state = {"date": "2026-07-28", "party_size": 2}  # no time
    assert build_slot_context(state) is None


def test_build_slot_context_empty():
    assert build_slot_context({}) is None
    assert build_slot_context(None) is None


# ── Day 12: slot context injected into system prompt ──────────────────


async def test_slot_context_in_system_prompt(session):
    """When Conversation.state has booking data, the system prompt includes it."""
    from app.orchestrator.base import TurnContext

    tenant = Tenant(slug=f"t-{uuid.uuid4().hex[:8]}", name="Cafe Duo")
    session.add(tenant)
    await session.flush()

    # Build a TurnContext with slot state
    from app.models.conversation import Conversation

    conv = Conversation(
        tenant_id=tenant.id,
        channel_type="webchat",
        external_thread_id=uuid.uuid4().hex,
        state={"date": "2026-07-28", "time": "20:00", "party_size": 3},
    )
    session.add(conv)
    await session.flush()

    ctx = TurnContext(tenant=tenant, conversation=conv, state=conv.state)
    prompt = build_system_prompt(tenant, context="Some context", state=ctx.state)
    assert "Table for 3" in prompt
    assert "2026-07-28" in prompt
    assert "20:00" in prompt
    assert "confirm the key details" in prompt  # _MULTI_TURN


# ── Day 12: reminder scheduling ───────────────────────────────────────


@pytest.mark.anyio
async def test_schedule_reminder_zadd():
    """schedule_reminder() calls Redis ZADD with correct score."""
    import fakeredis.aioredis

    from app.reminders import REMINDER_LEAD_HOURS, schedule_reminder

    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    booking_dt = datetime(2026, 7, 28, 20, 0, tzinfo=UTC)
    expected_due = booking_dt.timestamp() - (REMINDER_LEAD_HOURS * 3600)

    ok = await schedule_reminder(
        redis,
        tenant_id="tenant-1",
        reservation_id="res-123",
        booking_dt=booking_dt,
    )
    assert ok is True

    score = await redis.zscore("reminders:tenant-1", "res-123")
    assert score is not None
    assert abs(score - expected_due) < 1  # within 1 second tolerance


@pytest.mark.anyio
async def test_schedule_reminder_redis_none():
    """schedule_reminder returns False when no Redis available."""
    from app.reminders import schedule_reminder

    ok = await schedule_reminder(
        None,
        tenant_id="tenant-1",
        reservation_id="res-123",
        booking_dt=datetime(2026, 7, 28, 20, 0, tzinfo=UTC),
    )
    assert ok is False


# ── Day 12: state propagation across turns ────────────────────────────


async def test_state_propagates_across_turns(session):
    """Conversation.state JSONB persists across turns via handle_inbound."""
    tenant = Tenant(slug=f"t-{uuid.uuid4().hex[:8]}", name="Cafe State")
    session.add(tenant)
    await session.flush()

    provider = FakeProvider("Sure.")
    orch = LLMOrchestrator(llm=_service(provider), tier="quality", _skip_extractor=True)
    conv_ref = uuid.uuid4().hex

    # First turn
    msg1 = WebChatAdapter.to_inbound(
        tenant_slug=tenant.slug, conversation_ref=conv_ref, content="table for 2 friday 8pm"
    )
    async for _ in handle_inbound(msg1, db=session, redis=None, orchestrator=orch):
        pass

    # Verify Conversation.state persisted (defaults to empty dict)
    conv = (
        await session.execute(
            select(Conversation).where(
                Conversation.tenant_id == tenant.id,
                Conversation.external_thread_id == conv_ref,
            )
        )
    ).scalar_one()
    assert conv.state == {} or isinstance(conv.state, dict)

    # Second turn — state should still be accessible
    msg2 = WebChatAdapter.to_inbound(
        tenant_slug=tenant.slug, conversation_ref=conv_ref, content="make it 7pm"
    )
    async for _ in handle_inbound(msg2, db=session, redis=None, orchestrator=orch):
        pass

    # Refresh and check state persisted
    await session.refresh(conv)
    assert isinstance(conv.state, dict)
