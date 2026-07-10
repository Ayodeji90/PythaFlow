"""Anthropic wrapper — the only file in the codebase that imports the
anthropic SDK. If the SDK changes, changes stay inside this file."""

import os

from ..llm_service import LLMService

DEFAULT_MODELS = {
    "fast": "claude-haiku-4-5-20251001",
    "quality": "claude-sonnet-5",
}


class AnthropicService(LLMService):
    name = "anthropic"

    def __init__(self):
        import anthropic
        self._client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        self._models = {
            "fast": os.getenv("LLM_MODEL_FAST") or DEFAULT_MODELS["fast"],
            "quality": os.getenv("LLM_MODEL_QUALITY") or DEFAULT_MODELS["quality"],
        }

    def generate(self, prompt: str, *, tier: str = "quality",
                 max_tokens: int = 700) -> str:
        resp = self._client.messages.create(
            model=self._models.get(tier, self._models["quality"]),
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text
