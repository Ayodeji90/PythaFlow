"""FailoverProvider tests — every failover path across generate / generate_with_tools / stream.

Covers:
  - Constructor rejection of empty backends
  - models property
  - generate: happy, failover, timeout, all-fail
  - generate_with_tools: happy, failover, all-fail
  - stream: happy, failover, empty-stream, all-fail
  - _reason classification
  - aclose error tolerance
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.llm.base import LLMMessage, LLMProvider, LLMResult, LLMToolResult, ToolDefinition
from app.llm.providers.failover import Backend, FailoverProvider


# ── Mock provider factory ────────────────────────────────────────────────────


class _MockProvider(LLMProvider):
    """A stub provider that returns a canned result or raises on command."""

    def __init__(
        self,
        *,
        name: str = "mock",
        result: LLMResult | None = None,
        tool_result: LLMToolResult | None = None,
        stream_chunks: list[str] | None = None,
        exc: Exception | None = None,
        fail_count: int = 0,
        aclose_exc: Exception | None = None,
    ) -> None:
        self.name = name
        self._result = result
        self._tool_result = tool_result
        self._stream_chunks = stream_chunks
        self._exc = exc
        self._call_count = 0
        self._fail_count = fail_count  # fail N times, then succeed
        self._closed = False
        self._aclose_exc = aclose_exc

    async def generate(
        self,
        messages: list[LLMMessage],  # noqa: ARG002
        **kwargs: Any,
    ) -> LLMResult:
        self._call_count += 1
        if self._exc and (self._fail_count <= 0 or self._call_count <= self._fail_count):
            raise self._exc
        if self._result is not None:
            return self._result
        return LLMResult(text=f"reply-from-{self.name}", model=kwargs.get("model", "?"))

    async def generate_with_tools(
        self,
        messages: list[LLMMessage],  # noqa: ARG002
        **kwargs: Any,
    ) -> LLMToolResult:
        self._call_count += 1
        if self._exc and (self._fail_count <= 0 or self._call_count <= self._fail_count):
            raise self._exc
        if self._tool_result is not None:
            return self._tool_result
        return LLMToolResult(text=f"tool-reply-from-{self.name}")

    async def stream(
        self,
        messages: list[LLMMessage],  # noqa: ARG002
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        self._call_count += 1
        if self._exc and (self._fail_count <= 0 or self._call_count <= self._fail_count):
            raise self._exc
        if self._stream_chunks is not None:
            for c in self._stream_chunks:
                yield c
        else:
            yield f"streamed-from-{self.name}"

    async def aclose(self) -> None:
        self._closed = True
        if self._aclose_exc:
            raise self._aclose_exc

    @staticmethod
    def _make_result(text: str = "ok", model: str = "m1") -> LLMResult:
        return LLMResult(text=text, model=model, usage={"total_tokens": 10})

    @staticmethod
    def _make_tool_result(text: str = "tool-ok") -> LLMToolResult:
        return LLMToolResult(text=text)


# ── Constructor ──────────────────────────────────────────────────────────────


class TestConstructor:
    def test_empty_backends_raises(self):
        with pytest.raises(ValueError, match="at least one backend"):
            FailoverProvider([], attempt_timeout=5)

    def test_single_backend(self):
        fp = FailoverProvider(
            [Backend(_MockProvider(name="a"), "model-a")],
            attempt_timeout=10,
        )
        assert fp.name == "failover"
        assert fp.models == ["model-a"]
        assert fp._attempt_timeout == 10

    def test_multiple_backends(self):
        fp = FailoverProvider(
            [
                Backend(_MockProvider(name="a"), "model-a"),
                Backend(_MockProvider(name="b"), "model-b"),
            ],
            attempt_timeout=5,
        )
        assert fp.models == ["model-a", "model-b"]

    def test_custom_name(self):
        fp = FailoverProvider(
            [Backend(_MockProvider(name="a"), "m1")],
            attempt_timeout=5,
            name="azure_failover",
        )
        assert fp.name == "azure_failover"


# ── generate ─────────────────────────────────────────────────────────────────


class TestGenerate:
    async def test_first_backend_succeeds(self):
        p1 = _MockProvider(result=_MockProvider._make_result(text="hello"))
        p2 = _MockProvider(result=_MockProvider._make_result(text="world"))
        fp = FailoverProvider(
            [Backend(p1, "m1"), Backend(p2, "m2")],
            attempt_timeout=5,
        )
        result = await fp.generate([LLMMessage(role="user", content="hi")])
        assert result.text == "hello"
        assert p1._call_count == 1
        assert p2._call_count == 0  # never tried

    async def test_failover_to_second_backend(self):
        p1 = _MockProvider(exc=RuntimeError("down"))
        p2 = _MockProvider(result=_MockProvider._make_result(text="recovered"))
        fp = FailoverProvider(
            [Backend(p1, "m1"), Backend(p2, "m2")],
            attempt_timeout=30,
        )
        result = await fp.generate([LLMMessage(role="user", content="hi")])
        assert result.text == "recovered"
        assert p1._call_count == 1
        assert p2._call_count == 1

    async def test_all_backends_fail(self):
        p1 = _MockProvider(exc=RuntimeError("boom"))
        p2 = _MockProvider(exc=ValueError("crash"))
        fp = FailoverProvider(
            [Backend(p1, "m1"), Backend(p2, "m2")],
            attempt_timeout=5,
        )
        with pytest.raises(RuntimeError, match="All 2 LLM backends failed"):
            await fp.generate([LLMMessage(role="user", content="hi")])

    async def test_timeout_triggers_failover(self):
        async def _slow(*args, **kwargs):  # noqa: ANN002
            await asyncio.sleep(3600)
            return LLMResult(text="never", model="x")

        p1 = _MockProvider()
        p1.generate = _slow  # type: ignore[method-assign]
        p2 = _MockProvider(result=LLMResult(text="fast", model="m2"))
        fp = FailoverProvider(
            [Backend(p1, "m1"), Backend(p2, "m2")],
            attempt_timeout=0.01,  # very aggressive timeout
        )
        result = await fp.generate([LLMMessage(role="user", content="hi")])
        assert result.text == "fast"

    async def test_timeout_is_last_backend(self):
        async def _slow(*args, **kwargs):  # noqa: ANN002
            await asyncio.sleep(3600)

        p1 = _MockProvider()
        p1.generate = _slow  # type: ignore[method-assign]
        fp = FailoverProvider(
            [Backend(p1, "m1")],
            attempt_timeout=0.01,
        )
        with pytest.raises(RuntimeError, match="All 1 LLM backends failed"):
            await fp.generate([LLMMessage(role="user", content="hi")])


# ── generate_with_tools ──────────────────────────────────────────────────────


class TestGenerateWithTools:
    async def test_first_backend_succeeds(self):
        p1 = _MockProvider(tool_result=_MockProvider._make_tool_result())
        p2 = _MockProvider()
        fp = FailoverProvider(
            [Backend(p1, "m1"), Backend(p2, "m2")],
            attempt_timeout=5,
        )
        result = await fp.generate_with_tools(
            [LLMMessage(role="user", content="hi")],
            tools=[ToolDefinition(name="foo", description="bar", parameters={"type": "object"})],
        )
        assert result.text == "tool-ok"
        assert p2._call_count == 0

    async def test_failover_to_second(self):
        p1 = _MockProvider(exc=ConnectionError("refused"))
        p2 = _MockProvider(tool_result=LLMToolResult(text="ok-from-2"))
        fp = FailoverProvider(
            [Backend(p1, "m1"), Backend(p2, "m2")],
            attempt_timeout=30,
        )
        result = await fp.generate_with_tools(
            [LLMMessage(role="user", content="hi")],
            tools=[ToolDefinition(name="foo", description="bar", parameters={"type": "object"})],
        )
        assert result.text == "ok-from-2"

    async def test_all_fail(self):
        fp = FailoverProvider(
            [Backend(_MockProvider(exc=OSError("e1")), "m1")],
            attempt_timeout=5,
        )
        with pytest.raises(RuntimeError, match="All 1 LLM backends failed"):
            await fp.generate_with_tools(
                [LLMMessage(role="user", content="hi")],
                tools=[],
            )


# ── stream ───────────────────────────────────────────────────────────────────


class TestStream:
    async def test_first_backend_succeeds(self):
        p1 = _MockProvider(stream_chunks=["a", "b", "c"])
        p2 = _MockProvider(stream_chunks=["d"])
        fp = FailoverProvider(
            [Backend(p1, "m1"), Backend(p2, "m2")],
            attempt_timeout=5,
        )
        chunks = [c async for c in fp.stream([LLMMessage(role="user", content="hi")])]
        assert chunks == ["a", "b", "c"]
        assert p2._call_count == 0

    async def test_failover_to_second(self):
        p1 = _MockProvider(exc=ConnectionError("refused"))
        p2 = _MockProvider(stream_chunks=["fallback"])
        fp = FailoverProvider(
            [Backend(p1, "m1"), Backend(p2, "m2")],
            attempt_timeout=30,
        )
        chunks = [c async for c in fp.stream([LLMMessage(role="user", content="hi")])]
        assert chunks == ["fallback"]

    async def test_empty_stream_returns_immediately(self):
        """StopAsyncIteration on first __anext__() → return without yielding."""
        p1 = _MockProvider(stream_chunks=[])  # empty → immediate StopAsyncIteration
        fp = FailoverProvider(
            [Backend(p1, "m1")],
            attempt_timeout=5,
        )
        chunks = [c async for c in fp.stream([LLMMessage(role="user", content="hi")])]
        assert chunks == []  # StopAsyncIteration bypasses, no yield

    async def test_all_backends_fail_before_first_token(self):
        p1 = _MockProvider(exc=RuntimeError("e1"))
        p2 = _MockProvider(exc=ValueError("e2"))
        fp = FailoverProvider(
            [Backend(p1, "m1"), Backend(p2, "m2")],
            attempt_timeout=5,
        )
        with pytest.raises(RuntimeError, match="All 2 LLM backends failed"):
            _ = [c async for c in fp.stream([LLMMessage(role="user", content="hi")])]

    async def test_timeout_before_first_token(self):
        async def _slow(*args, **kwargs):  # noqa: ANN002
            await asyncio.sleep(3600)
            yield "late"  # pragma: no cover

        p1 = _MockProvider()
        p1.stream = _slow  # type: ignore[method-assign]
        p2 = _MockProvider(stream_chunks=["fast"])
        fp = FailoverProvider(
            [Backend(p1, "m1"), Backend(p2, "m2")],
            attempt_timeout=0.01,
        )
        chunks = [c async for c in fp.stream([LLMMessage(role="user", content="hi")])]
        assert chunks == ["fast"]


# ── _reason ──────────────────────────────────────────────────────────────────


class TestReason:
    def test_timeout_exception(self):
        assert FailoverProvider._reason(asyncio.TimeoutError()) == "timeout"
        assert FailoverProvider._reason(TimeoutError()) == "timeout"

    def test_other_exception(self):
        assert (
            FailoverProvider._reason(RuntimeError("oops"))
            == "RuntimeError: oops"
        )


# ── aclose ───────────────────────────────────────────────────────────────────


class TestAclose:
    async def test_closes_all_backends(self):
        p1 = _MockProvider()
        p2 = _MockProvider()
        fp = FailoverProvider(
            [Backend(p1, "m1"), Backend(p2, "m2")],
            attempt_timeout=5,
        )
        await fp.aclose()
        assert p1._closed
        assert p2._closed

    async def test_tolerates_acloser_error(self):
        p1 = _MockProvider(aclose_exc=RuntimeError("cleanup failed"))
        p2 = _MockProvider()
        fp = FailoverProvider(
            [Backend(p1, "m1"), Backend(p2, "m2")],
            attempt_timeout=5,
        )
        await fp.aclose()  # must not raise
        assert p2._closed