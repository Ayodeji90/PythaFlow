"""Provider wrapper for any OpenAI-compatible Chat Completions API.

One wrapper covers a huge range of vendors just by pointing `base_url` at them:
NVIDIA NIM, OpenAI, Groq, Mistral, Together, Fireworks, local Ollama, etc. This
is the only file in the LLM seam that imports a vendor SDK (`openai`)."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence

from ..base import (
    LLMMessage,
    LLMProvider,
    LLMResult,
    LLMToolResult,
    ToolCall,
    ToolDefinition,
)


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        name: str = "openai_compatible",
        timeout: float | None = None,
        api_version: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        # Imported lazily so the module (and the app) load even if the SDK is
        # absent until dependencies are installed.
        from openai import AsyncOpenAI

        self.name = name
        # api_key is a placeholder when unset — we never call the API without a
        # real key (the smoke test and callers guard on that). `timeout` bounds
        # request duration so a slow/unreachable provider can't stall our work.
        #
        # api_version / extra_headers exist for Azure AI Foundry: its Inference
        # endpoints (…/models) need `?api-version=` and authenticate via an
        # `api-key` header. Plain OpenAI-compatible endpoints leave both blank.
        client_kwargs: dict = {
            "api_key": api_key or "not-set",
            "base_url": base_url,
            "timeout": timeout,
        }
        if api_version:
            client_kwargs["default_query"] = {"api-version": api_version}
        if extra_headers:
            client_kwargs["default_headers"] = extra_headers
        self._client = AsyncOpenAI(**client_kwargs)

    @staticmethod
    def _payload(messages: Sequence[LLMMessage], system: str | None) -> list[dict]:
        payload: list[dict] = []
        if system:
            payload.append({"role": "system", "content": system})
        for m in messages:
            msg: dict = {"role": m.role}

            # Content: null for assistant messages that carry tool_calls without text
            if m.tool_calls and not m.content:
                msg["content"] = None
            else:
                msg["content"] = m.content

            if m.tool_call_id:
                msg["tool_call_id"] = m.tool_call_id
            if m.name:
                msg["name"] = m.name
            if m.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in m.tool_calls
                ]
            payload.append(msg)
        return payload

    @staticmethod
    def _tool_schema(tools: list[ToolDefinition]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

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
        resp = await self._client.chat.completions.create(
            model=model,
            messages=self._payload(messages, system),
            tools=self._tool_schema(tools) if tools else None,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        msg = resp.choices[0].message
        text = (msg.content or "").strip() or None
        tool_calls: list[ToolCall] | None = None
        if msg.tool_calls:
            tool_calls = [
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments),
                )
                for tc in msg.tool_calls
            ]
        return LLMToolResult(text=text, tool_calls=tool_calls or None)

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
