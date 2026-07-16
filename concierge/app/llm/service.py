"""LLMService — the stable, app-facing interface.

The app core (routers, and from Day 4 the orchestrator) depends ONLY on this.
It maps a quality *tier* to a concrete model and delegates to whatever provider
wrapper is configured. Swapping vendors never touches a single caller."""
from __future__ import annotations

from collections.abc import Sequence

from .base import LLMMessage, LLMProvider


class LLMService:
    def __init__(
        self,
        provider: LLMProvider,
        model_fast: str,
        model_quality: str,
        *,
        temperature: float = 0.4,
        max_tokens: int = 1024,
    ) -> None:
        self._provider = provider
        self._models = {"fast": model_fast, "quality": model_quality}
        self._temperature = temperature
        self._max_tokens = max_tokens

    @property
    def provider_name(self) -> str:
        return self._provider.name

    def model_for(self, tier: str) -> str:
        return self._models.get(tier, self._models["quality"])

    async def generate(
        self,
        messages: str | Sequence[LLMMessage],
        *,
        tier: str = "quality",
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Generate a completion. `messages` may be a bare string (treated as a
        single user turn) or a sequence of LLMMessage."""
        if isinstance(messages, str):
            messages = [LLMMessage(role="user", content=messages)]
        result = await self._provider.generate(
            messages,
            model=self.model_for(tier),
            system=system,
            temperature=self._temperature if temperature is None else temperature,
            max_tokens=self._max_tokens if max_tokens is None else max_tokens,
        )
        return result.text

    async def aclose(self) -> None:
        await self._provider.aclose()
