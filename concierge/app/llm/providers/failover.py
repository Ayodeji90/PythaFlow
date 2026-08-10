"""Failover across multiple LLM backends.

Wraps an ordered list of (provider, model) backends. Each call tries backend 1;
if it raises OR exceeds `attempt_timeout` seconds, the router logs it and routes
to the next backend, and so on. If every backend fails, it raises.

Built for Azure AI Foundry, where several serverless deployments (DeepSeek, Grok,
Kimi, …) can back one concierge with automatic fallback — so a slow or unavailable
model never stalls a guest reply.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from ..base import LLMMessage, LLMProvider, LLMResult, LLMToolResult, ToolDefinition

log = logging.getLogger("concierge.llm.failover")


@dataclass
class Backend:
    """One failover target: a provider wrapper + the model name it should call."""

    provider: LLMProvider
    model: str


class FailoverProvider(LLMProvider):
    """Try each backend in order; fall over on error or per-attempt timeout."""

    def __init__(
        self,
        backends: list[Backend],
        *,
        attempt_timeout: float,
        name: str = "failover",
    ) -> None:
        if not backends:
            raise ValueError("FailoverProvider needs at least one backend")
        self.name = name
        self._backends = backends
        self._attempt_timeout = attempt_timeout

    @property
    def models(self) -> list[str]:
        return [b.model for b in self._backends]

    async def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        model: str | None = None,     # ignored — each backend uses its own model
        system: str | None = None,
        temperature: float = 0.4,
        max_tokens: int = 1024,
    ) -> LLMResult:
        last_exc: Exception | None = None
        for b in self._backends:
            try:
                return await asyncio.wait_for(
                    b.provider.generate(
                        messages,
                        model=b.model,
                        system=system,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    ),
                    timeout=self._attempt_timeout,
                )
            except Exception as exc:  # noqa: BLE001 — any failure routes to the next backend
                last_exc = exc
                log.warning(
                    "LLM backend %r failed (%s) — routing to next",
                    b.model, self._reason(exc),
                )
        raise RuntimeError(
            f"All {len(self._backends)} LLM backends failed"
        ) from last_exc

    async def generate_with_tools(
        self,
        messages: Sequence[LLMMessage],
        *,
        model: str | None = None,
        tools: list[ToolDefinition],
        system: str | None = None,
        temperature: float = 0.4,
        max_tokens: int = 1024,
    ) -> LLMToolResult:
        last_exc: Exception | None = None
        for b in self._backends:
            try:
                return await asyncio.wait_for(
                    b.provider.generate_with_tools(
                        messages,
                        model=b.model,
                        tools=tools,
                        system=system,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    ),
                    timeout=self._attempt_timeout,
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                log.warning(
                    "LLM backend %r failed on tool call (%s) — routing to next",
                    b.model, self._reason(exc),
                )
        raise RuntimeError(
            f"All {len(self._backends)} LLM backends failed (tools)"
        ) from last_exc

    async def stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        model: str | None = None,
        system: str | None = None,
        temperature: float = 0.4,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        # Failover is only possible up to the first token — once we start
        # streaming a backend's reply we commit to it (re-issuing would duplicate
        # tokens). The time-to-first-token is what the timeout bounds.
        last_exc: Exception | None = None
        for b in self._backends:
            gen = b.provider.stream(
                messages,
                model=b.model,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
            ).__aiter__()
            try:
                first = await asyncio.wait_for(
                    gen.__anext__(), timeout=self._attempt_timeout
                )
            except StopAsyncIteration:
                return  # backend produced an empty but successful stream
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                log.warning(
                    "LLM backend %r failed before first token (%s) — routing to next",
                    b.model, self._reason(exc),
                )
                continue
            yield first
            async for chunk in gen:
                yield chunk
            return
        raise RuntimeError(
            f"All {len(self._backends)} LLM backends failed (stream)"
        ) from last_exc

    @staticmethod
    def _reason(exc: Exception) -> str:
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
            return "timeout"
        return f"{type(exc).__name__}: {exc}"

    async def aclose(self) -> None:
        for b in self._backends:
            try:
                await b.provider.aclose()
            except Exception:  # noqa: BLE001 — closing one shouldn't block the rest
                pass
