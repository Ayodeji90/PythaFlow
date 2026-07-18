"""Day-4: the LLM orchestrator, tested against a FAKE provider — no network, no
key. This is the payoff of the provider seam: we inject a stub and assert
streaming, persona wiring, and multi-turn context deterministically."""
import uuid
from collections.abc import AsyncIterator, Sequence

from sqlalchemy import select

from app.channels.base import handle_inbound
from app.channels.webchat import WebChatAdapter
from app.llm.base import LLMMessage, LLMProvider, LLMResult
from app.llm.service import LLMService
from app.models import Message, Tenant
from app.models.enums import MessageRole
from app.orchestrator.engine import LLMOrchestrator


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


def _service(provider: FakeProvider) -> LLMService:
    return LLMService(provider, "fake-fast", "fake-quality")


async def test_streams_tokens_and_persists(session):
    tenant = Tenant(slug=f"t-{uuid.uuid4().hex[:8]}", name="Bella Vista", brand_voice="Playful.")
    session.add(tenant)
    await session.flush()

    provider = FakeProvider("Welcome to Bella Vista!")
    orch = LLMOrchestrator(llm=_service(provider), tier="quality")

    conv_ref = uuid.uuid4().hex
    msg = WebChatAdapter.to_inbound(
        tenant_slug=tenant.slug, conversation_ref=conv_ref, content="hi there"
    )
    chunks = [
        c
        async for c in handle_inbound(msg, db=session, redis=None, orchestrator=orch)
    ]
    types = [c.type for c in chunks]

    # streamed as tokens, then done
    assert "token" in types
    assert types[-1] == "done"
    reply = "".join(c.content for c in chunks if c.type == "token")
    assert reply.strip() == "Welcome to Bella Vista!"

    # persona wiring: the system prompt carried the tenant's name + brand voice
    assert "Bella Vista" in provider.last_system
    assert "Playful." in provider.last_system

    # the assistant turn was persisted (pipeline concatenated the tokens)
    rows = (
        await session.execute(
            select(Message)
            .where(Message.conversation_id.isnot(None), Message.tenant_id == tenant.id)
            .order_by(Message.created_at)
        )
    ).scalars().all()
    assert [r.role for r in rows] == [MessageRole.guest, MessageRole.assistant]
    assert rows[1].content.strip() == "Welcome to Bella Vista!"


async def test_multi_turn_sees_prior_messages(session):
    tenant = Tenant(slug=f"t-{uuid.uuid4().hex[:8]}", name="Cafe Uno")
    session.add(tenant)
    await session.flush()

    provider = FakeProvider("Sure.")
    orch = LLMOrchestrator(llm=_service(provider), tier="quality")
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
