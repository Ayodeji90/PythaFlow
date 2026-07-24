"""Types + the provider-wrapper contract. This module has no vendor imports."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field


@dataclass
class LLMMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMResult:
    text: str
    model: str
    usage: dict = field(default_factory=dict)


from typing import Optional
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMToolResult:
    text: Optional[str]
    tool_calls: Optional[list[ToolCall]]

class LLMProvider(ABC):
    """AI Provider Wrapper — one thin adapter per vendor API shape.

    Implementations live in `app/llm/providers/`. They are the *only* place a
    vendor SDK is imported. Adding a vendor whose API is not OpenAI-shaped
    (e.g. Anthropic) means adding one new subclass here — nothing else changes.
    """

    name: str = "base"

    @abstractmethod
    async def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        model: str,
        system: str | None = None,
        temperature: float = 0.4,
        max_tokens: int = 1024,
    ) -> LLMResult:
        ...

    async def stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        model: str,
        system: str | None = None,
        temperature: float = 0.4,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        """Yield the reply in fragments as they arrive.

        Default implementation falls back to a single non-streamed call, so a
        vendor without streaming still works through the same interface — it just
        arrives in one piece.
        """
        result = await self.generate(
            messages,
            model=model,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        yield result.text

    async def aclose(self) -> None:  # pragma: no cover - default no-op
        return None
