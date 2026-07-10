"""Wrapper for any OpenAI-compatible chat API — OpenAI itself, Groq,
Mistral, Together, or a local Ollama. Plain REST via httpx, so there is
no SDK to break. Point it at a vendor with:

    OPENAI_API_KEY=...
    OPENAI_BASE_URL=https://api.openai.com/v1   (default; e.g. Ollama:
                                                 http://localhost:11434/v1)
    LLM_MODEL_FAST / LLM_MODEL_QUALITY           to name the models
"""

import os

import httpx

from ..llm_service import LLMService

DEFAULT_MODELS = {"fast": "gpt-4o-mini", "quality": "gpt-4o"}


class OpenAICompatibleService(LLMService):
    name = "openai"

    def __init__(self):
        self._base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self._key = os.getenv("OPENAI_API_KEY", "")
        self._models = {
            "fast": os.getenv("LLM_MODEL_FAST") or DEFAULT_MODELS["fast"],
            "quality": os.getenv("LLM_MODEL_QUALITY") or DEFAULT_MODELS["quality"],
        }

    def generate(self, prompt: str, *, tier: str = "quality",
                 max_tokens: int = 700) -> str:
        resp = httpx.post(
            f"{self._base}/chat/completions",
            headers={"Authorization": f"Bearer {self._key}"},
            json={
                "model": self._models.get(tier, self._models["quality"]),
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
