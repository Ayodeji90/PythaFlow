"""Recording and replay providers for deterministic eval harness.

Two complementary providers built on the ``LLMProvider`` seam:

RecordingProvider
    Wraps a real provider and records every ``LLMToolResult``, along with the
    system prompt and messages that produced it. Save to YAML for later replay.

ReplayProvider
    Loads a previously saved recording and returns the exact same results in
    order — no network, no API keys, fully deterministic.

FakeEmbedder
    A dummy embedder that returns a zero vector, used when the eval doesn't
    need real retrieval but the orchestrator still calls the embed path.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.llm.base import (
    LLMMessage,
    LLMProvider,
    LLMResult,
    LLMToolResult,
    ToolCall,
)

# ── Fake embedder for retrieval bypass ───────────────────────────────────


class FakeEmbedder:
    """Returns a zero vector of the configured dimension.

    This lets the orchestrator's ``retrieve()`` step succeed (finding chunks
    with zero embeddings at distance 0) without calling any real embedding API.
    """

    def __init__(self, dim: int = 1024) -> None:
        self._dim = dim

    async def embed(self, text: str) -> list[float]:
        return [0.0] * self._dim

    async def embed_query(self, text: str) -> list[float]:
        return [0.0] * self._dim

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self._dim for _ in texts]

    async def aclose(self) -> None:
        pass


# ── Recording provider ───────────────────────────────────────────────────


class RecordingProvider(LLMProvider):
    """Wraps a real provider and records all LLM interactions per turn.

    Records capture the system prompt, messages, and the LLMToolResult returned.
    Call ``save_recording(path)`` after the dialogue completes to persist.
    """

    name = "recording"

    def __init__(self, inner: LLMProvider) -> None:
        self._inner = inner
        self.recordings: list[dict[str, Any]] = []
        self.last_system: str | None = None
        self.last_messages: list[LLMMessage] = []

    async def generate(self, messages, *, model, system=None, temperature=0.4, max_tokens=1024):
        self.last_system = system
        self.last_messages = list(messages)
        result = await self._inner.generate(
            messages, model=model, system=system, temperature=temperature, max_tokens=max_tokens
        )
        self.recordings.append({
            "type": "generate",
            "system": system,
            "result": _result_to_dict(result),
        })
        return result

    async def stream(self, messages, *, model, system=None, temperature=0.4, max_tokens=1024):
        self.last_system = system
        self.last_messages = list(messages)
        chunks: list[str] = []
        async for chunk in self._inner.stream(
            messages, model=model, system=system, temperature=temperature, max_tokens=max_tokens
        ):
            chunks.append(chunk)
            yield chunk
        self.recordings.append({
            "type": "stream",
            "system": system,
            "result": {"text": "".join(chunks)},
        })

    async def generate_with_tools(
        self,
        messages,
        *,
        model,
        tools=None,
        system=None,
        temperature=0.4,
        max_tokens=1024,
    ):
        self.last_system = system
        self.last_messages = list(messages)
        result = await self._inner.generate_with_tools(
            messages,
            model=model,
            tools=tools or [],
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self.recordings.append({
            "type": "generate_with_tools",
            "system": system,
            "result": _result_to_dict(result),
        })
        return result

    def save_recording(self, path: str | Path) -> None:
        """Persist recorded interactions as YAML."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(self.recordings, f, default_flow_style=False)


# ── Replay provider ──────────────────────────────────────────────────────


class ReplayProvider(LLMProvider):
    """Plays back pre-recorded LLM responses deterministically.

    Loads a YAML recording and returns the exact same ``LLMToolResult`` /
    ``LLMResult`` objects in order. Tracks system prompt and messages for
    scoring assertions via ``last_system`` / ``last_messages``.
    """

    name = "replay"

    def __init__(self, recordings: list[dict]) -> None:
        self._recordings = list(recordings)
        self._index = 0
        self.last_system: str | None = None
        self.last_messages: list[LLMMessage] = []

    @classmethod
    def load(cls, path: str | Path) -> ReplayProvider:
        """Load recordings from a YAML file."""
        path = Path(path)
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(data or [])

    def _next(self) -> dict:
        if self._index >= len(self._recordings):
            raise RuntimeError(
                f"Replay exhausted: {self._index} recordings available, "
                f"but provider was called again. "
                f"Has the dialogue changed since the recording was made?"
            )
        entry = self._recordings[self._index]
        self._index += 1
        return entry

    async def generate(self, messages, *, model, system=None, temperature=0.4, max_tokens=1024):
        self.last_system = system
        self.last_messages = list(messages)
        entry = self._next()
        result_data = entry["result"]
        return LLMResult(text=result_data.get("text", ""), model=result_data.get("model", model))

    async def stream(self, messages, *, model, system=None, temperature=0.4, max_tokens=1024):
        self.last_system = system
        self.last_messages = list(messages)
        entry = self._next()
        text = entry.get("result", {}).get("text", "")
        yield text

    async def generate_with_tools(
        self,
        messages,
        *,
        model,
        tools=None,
        system=None,
        temperature=0.4,
        max_tokens=1024,
    ):
        self.last_system = system
        self.last_messages = list(messages)
        entry = self._next()
        return _dict_to_result(entry["result"])


# ── Serialisation helpers ────────────────────────────────────────────────


def _result_to_dict(result: LLMToolResult | LLMResult) -> dict:
    if isinstance(result, LLMToolResult):
        d: dict = {"text": result.text}
        if result.tool_calls:
            d["tool_calls"] = [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in result.tool_calls
            ]
        return d
    # LLMResult or generic
    text = result.text if hasattr(result, "text") else ""
    return {"text": text, "model": getattr(result, "model", "")}


def _dict_to_result(d: dict) -> LLMToolResult:
    tool_calls = None
    if "tool_calls" in d and d["tool_calls"]:
        tool_calls = [
            ToolCall(
                id=tc["id"],
                name=tc["name"],
                arguments=tc.get("arguments", {}),
            )
            for tc in d["tool_calls"]
        ]
    return LLMToolResult(text=d.get("text"), tool_calls=tool_calls)