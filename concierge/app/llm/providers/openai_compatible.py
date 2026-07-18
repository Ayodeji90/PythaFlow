"""Provider wrapper for any OpenAI-compatible Chat Completions API.

One wrapper covers a huge range of vendors just by pointing `base_url` at them:
NVIDIA NIM, OpenAI, Groq, Mistral, Together, Fireworks, local Ollama, etc. This
is the only file in the LLM seam that imports a vendor SDK (`openai`)."""
from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from ..base import LLMMessage, LLMProvider, LLMResult


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        name: str = "openai_compatible",
        timeout: float | None = None,
    ) -> None:
        # Imported lazily so the module (and the app) load even if the SDK is
        # absent until dependencies are installed.
        from openai import AsyncOpenAI

        self.name = name
        # api_key is a placeholder when unset — we never call the API without a
        # real key (the smoke test and callers guard on that). `timeout` bounds
        # request duration so a slow/unreachable provider can't stall our work.
        self._client = AsyncOpenAI(
            api_key=api_key or "not-set", base_url=base_url, timeout=timeout
        )

    @staticmethod
    def _payload(messages: Sequence[LLMMessage], system: str | None) -> list[dict]:
        payload: list[dict] = []
        if system:
            payload.append({"role": "system", "content": system})
        payload.extend({"role": m.role, "content": m.content} for m in messages)
        return payload

    async def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        model: str,
        system: str | None = None,
        temperature: float = 0.4,
        max_tokens: int = 1024,
    ) -> LLMResult:
        resp = await self._client.chat.completions.create(
            model=model,
            messages=self._payload(messages, system),
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = (resp.choices[0].message.content or "").strip()
        usage = resp.usage.model_dump() if resp.usage else {}
        return LLMResult(text=text, model=model, usage=usage)

    async def stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        model: str,
        system: str | None = None,
        temperature: float = 0.4,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        stream = await self._client.chat.completions.create(
            model=model,
            messages=self._payload(messages, system),
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content

    async def aclose(self) -> None:
        await self._client.close()
