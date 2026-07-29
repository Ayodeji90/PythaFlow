"""Chooses and constructs the provider from Settings, then wraps it in the
stable LLMService. This is the single place that knows which vendors exist."""
from __future__ import annotations

from ..config import Settings, get_settings
from .providers.openai_compatible import OpenAICompatibleProvider
from .service import LLMService

# Default base URLs for OpenAI-compatible vendors. Add a vendor of this shape =
# add one line. Add a vendor of a different shape (e.g. Anthropic) = add one new
# provider wrapper file and a branch below.
_OPENAI_COMPATIBLE_BASE_URLS: dict[str, str | None] = {
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "openai_compatible": None,  # requires LLM_BASE_URL
}


def build_llm_service(settings: Settings | None = None) -> LLMService:
    s = settings or get_settings()
    provider_key = s.LLM_PROVIDER.lower()

    if provider_key in ("azure_failover", "failover"):
        return _build_failover_service(s)

    if provider_key in _OPENAI_COMPATIBLE_BASE_URLS:
        base_url = s.LLM_BASE_URL or _OPENAI_COMPATIBLE_BASE_URLS[provider_key]
        if not base_url:
            raise ValueError(
                f"LLM_PROVIDER={provider_key!r} requires LLM_BASE_URL to be set."
            )
        provider = OpenAICompatibleProvider(
            api_key=s.LLM_API_KEY,
            base_url=base_url,
            name=provider_key,
            timeout=s.LLM_TIMEOUT,
        )
    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER {s.LLM_PROVIDER!r}. "
            f"Supported: {', '.join(_OPENAI_COMPATIBLE_BASE_URLS)}. "
            "For a non-OpenAI-shaped vendor (e.g. Anthropic), add a wrapper in "
            "app/llm/providers/ and a branch here."
        )

    return LLMService(
        provider,
        s.LLM_MODEL_FAST,
        s.LLM_MODEL_QUALITY,
        temperature=s.LLM_TEMPERATURE,
        max_tokens=s.LLM_MAX_TOKENS,
    )


def _build_failover_service(s: Settings) -> LLMService:
    """Build an LLMService backed by a FailoverProvider across the configured
    Azure AI Foundry deployments (tried in order, falling over on error/timeout)."""
    from .providers.failover import Backend, FailoverProvider

    backends_cfg = s.azure_foundry_backends()
    if not backends_cfg:
        raise ValueError(
            "LLM_PROVIDER=azure_failover requires at least "
            "AZURE_FOUNDRY_1_ENDPOINT + AZURE_FOUNDRY_1_MODEL (and usually _KEY)."
        )

    api_version = (s.AZURE_FOUNDRY_API_VERSION or "").strip() or None
    backends: list[Backend] = []
    for endpoint, key, model in backends_cfg:
        # Azure AI Inference endpoints authenticate via an `api-key` header (in
        # addition to the api-version query); plain OpenAI-compatible routes just
        # use the bearer key. Sending the header only when api_version is set keeps
        # non-Azure endpoints clean.
        extra_headers = {"api-key": key} if (api_version and key) else None
        provider = OpenAICompatibleProvider(
            api_key=key,
            base_url=endpoint,
            name=f"azure:{model}",
            timeout=s.LLM_TIMEOUT,
            api_version=api_version,
            extra_headers=extra_headers,
        )
        backends.append(Backend(provider=provider, model=model))

    failover = FailoverProvider(
        backends,
        attempt_timeout=s.AZURE_FOUNDRY_ATTEMPT_TIMEOUT,
        name="azure_failover",
    )
    # The failover provider ignores the tier→model mapping (each backend carries
    # its own model), so both tiers point at the primary for display/metadata.
    primary_model = backends[0].model
    return LLMService(
        failover,
        primary_model,
        primary_model,
        temperature=s.LLM_TEMPERATURE,
        max_tokens=s.LLM_MAX_TOKENS,
    )
