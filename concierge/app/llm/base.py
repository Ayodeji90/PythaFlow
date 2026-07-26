"""Types + the provider-wrapper contract. This module has no vendor imports."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMMessage:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str = ""
    tool_call_id: str | None = None   # for role="tool" — matches ToolCall.id
    name: str | None = None           # for role="tool" — the function name
    tool_calls: list[ToolCall] | None = None  # for role="assistant"


@dataclass
class LLMResult:
    text: str
    model: str
    usage: dict = field(default_factory=dict)


@dataclass
class ToolDefinition:
    """Schema for a tool the LLM may call — mirrors the OpenAI tools parameter."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema object


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMToolResult:
    """Result of a generate_with_tools call: either text, tool calls, or both."""

    text: str | None = None
    tool_calls: list[ToolCall] | None = None


class ToolsUnsupportedError(NotImplementedError):
    """Raised by providers that don't support tool calling."""

    def __init__(self, provider: str = "this provider") -> None:
        super().__init__(f"{provider} does not support tool calling")


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

    async def generate_with_tools(
        self,
        messages: Sequence[LLMMessage],
        *,
        model: str,
        tools: list[ToolDefinition],
        system: str | None = None,
        temperature: float = 0.4,
        max_tokens: int = 1024,
    ) -> LLMToolResult:
        """Generate a completion with tool calling.

        The default raises ToolsUnsupportedError — providers that support tool
        calling (OpenAI-shaped) override this method.
        """
        raise ToolsUnsupportedError(self.name)

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
