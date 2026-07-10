"""LLMService interface — the stable seam between app core and AI vendors.

App code (voice, marketing) talks to this interface only. Every vendor
SDK/API lives in its own wrapper under services/providers/. Switching
providers or models is a .env change, never an app-code change:

    LLM_PROVIDER=auto | anthropic | openai | none
    LLM_MODEL_FAST=...      (optional per-tier model override)
    LLM_MODEL_QUALITY=...

"auto" picks anthropic if ANTHROPIC_API_KEY is set, else openai if
OPENAI_API_KEY is set, else none (rule-based fallbacks keep the demo alive).
"""

import os
from abc import ABC, abstractmethod
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[4] / ".env")


class LLMService(ABC):
    """One method, two tiers. 'fast' = low-latency turns (voice);
    'quality' = best output (marketing copy). Each provider maps tiers
    to its own model ids."""

    name: str = "none"

    @abstractmethod
    def generate(self, prompt: str, *, tier: str = "quality",
                 max_tokens: int = 700) -> str:
        """Return the model's text for a single-turn prompt."""

    def available(self) -> bool:
        return True


class NullLLMService(LLMService):
    """No provider configured — callers use their rule-based fallbacks."""

    name = "none"

    def generate(self, prompt: str, *, tier: str = "quality",
                 max_tokens: int = 700) -> str:
        raise RuntimeError("No LLM provider configured")

    def available(self) -> bool:
        return False


_service: LLMService | None = None


def get_llm_service() -> LLMService:
    global _service
    if _service is None:
        _service = _build()
    return _service


def _build() -> LLMService:
    choice = os.getenv("LLM_PROVIDER", "auto").strip().lower()
    if choice == "auto":
        if os.getenv("ANTHROPIC_API_KEY"):
            choice = "anthropic"
        elif os.getenv("OPENAI_API_KEY"):
            choice = "openai"
        else:
            choice = "none"

    if choice == "anthropic":
        from .providers.anthropic_provider import AnthropicService
        return AnthropicService()
    if choice in ("openai", "openai-compatible"):
        from .providers.openai_compatible import OpenAICompatibleService
        return OpenAICompatibleService()
    return NullLLMService()
