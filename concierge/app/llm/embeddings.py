"""Embeddings seam — mirrors the LLM seam: a stable interface + a swappable
provider. NVIDIA's embedding API is OpenAI-compatible, so the provider is a thin
wrapper over the same `AsyncOpenAI` client.

`nv-embedqa-e5-v5` is an asymmetric *retrieval* model: passages (documents) and
queries are embedded with different `input_type`s, which materially improves
recall. We expose that as `embed_documents` vs `embed_query`.
"""
from __future__ import annotations

from typing import Literal, Protocol

from ..config import Settings, get_settings

InputType = Literal["passage", "query"]


class EmbeddingService(Protocol):
    dim: int

    async def embed(self, texts: list[str], *, input_type: InputType) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def aclose(self) -> None: ...


class OpenAICompatibleEmbeddings:
    """Works with NVIDIA NIM and OpenAI-style embedding endpoints."""

    def __init__(self, *, api_key: str, base_url: str, model: str, dim: int) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key or "not-set", base_url=base_url)
        self._model = model
        self.dim = dim

    async def embed(self, texts: list[str], *, input_type: InputType) -> list[list[float]]:
        if not texts:
            return []
        # NVIDIA needs input_type (passage|query); OpenAI ignores the extra field.
        resp = await self._client.embeddings.create(
            model=self._model,
            input=texts,
            extra_body={"input_type": input_type, "truncate": "END"},
        )
        return [d.embedding for d in resp.data]

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed([text], input_type="query"))[0]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self.embed(texts, input_type="passage")

    async def aclose(self) -> None:
        await self._client.close()


# Base URLs for OpenAI-compatible embedding vendors (parallel to the LLM factory).
_EMBED_BASE_URLS: dict[str, str | None] = {
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "openai": "https://api.openai.com/v1",
    "openai_compatible": None,
}


def build_embedding_service(settings: Settings | None = None) -> EmbeddingService:
    s = settings or get_settings()
    key = s.EMBED_PROVIDER.lower()
    if key not in _EMBED_BASE_URLS:
        raise ValueError(
            f"Unknown EMBED_PROVIDER {s.EMBED_PROVIDER!r}. "
            f"Supported: {', '.join(_EMBED_BASE_URLS)}."
        )
    # Reuse the LLM key/base-url when the embedding provider is the same vendor.
    base_url = _EMBED_BASE_URLS[key] or s.LLM_BASE_URL
    if not base_url:
        raise ValueError(f"EMBED_PROVIDER={key!r} needs a base URL.")
    return OpenAICompatibleEmbeddings(
        api_key=s.LLM_API_KEY, base_url=base_url, model=s.EMBED_MODEL, dim=s.EMBED_DIM
    )
