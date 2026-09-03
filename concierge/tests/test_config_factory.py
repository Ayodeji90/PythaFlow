"""Tests for config validation (azure_foundry_backends) and the LLM factory
(build_llm_service with azure_failover, unknown provider, etc.).

The aim is to cover the branches the FailoverProvider and router tests don't reach:
the config filtering logic and the factory routing.

NOTE: Every Settings() call passes _env_file=None and explicit Azure defaults so
these tests are hermetic — they never read from .env or the real environment.
"""
from __future__ import annotations

import pytest

from app.config import Settings

# ── Helpers ──────────────────────────────────────────────────────────────────


def _settings(**kwargs) -> Settings:
    """Create a Settings with all Azure Foundry vars cleared by default,
    so test assertions aren't polluted by the host's .env."""
    defaults = {
        "AZURE_FOUNDRY_1_ENDPOINT": "",
        "AZURE_FOUNDRY_1_KEY": "",
        "AZURE_FOUNDRY_1_MODEL": "",
        "AZURE_FOUNDRY_2_ENDPOINT": "",
        "AZURE_FOUNDRY_2_KEY": "",
        "AZURE_FOUNDRY_2_MODEL": "",
        "AZURE_FOUNDRY_3_ENDPOINT": "",
        "AZURE_FOUNDRY_3_KEY": "",
        "AZURE_FOUNDRY_3_MODEL": "",
        "_env_file": None,
    }
    defaults.update(kwargs)
    return Settings(**defaults)


# ── Config: azure_foundry_backends ───────────────────────────────────────────


class TestAzureFoundryBackends:
    def test_all_empty_returns_empty_list(self):
        s = _settings()
        assert s.azure_foundry_backends() == []

    def test_single_backend_configured(self):
        s = _settings(
            AZURE_FOUNDRY_1_ENDPOINT="https://e1.ai.azure.com/models",
            AZURE_FOUNDRY_1_KEY="k1",
            AZURE_FOUNDRY_1_MODEL="DeepSeek-V4",
        )
        backends = s.azure_foundry_backends()
        assert backends == [
            ("https://e1.ai.azure.com/models", "k1", "DeepSeek-V4"),
        ]

    def test_two_backends_with_gap(self):
        """Backend 1 and 3 set; backend 2 blank — only 1 and 3 returned."""
        s = _settings(
            AZURE_FOUNDRY_1_ENDPOINT="https://e1.ai.azure.com/models",
            AZURE_FOUNDRY_1_KEY="k1",
            AZURE_FOUNDRY_1_MODEL="m1",
            # backend 2 is intentionally blank
            AZURE_FOUNDRY_3_ENDPOINT="https://e3.ai.azure.com/models",
            AZURE_FOUNDRY_3_KEY="k3",
            AZURE_FOUNDRY_3_MODEL="m3",
        )
        backends = s.azure_foundry_backends()
        assert len(backends) == 2
        assert backends[0][2] == "m1"
        assert backends[1][2] == "m3"

    def test_endpoint_without_model_skipped(self):
        s = _settings(
            AZURE_FOUNDRY_1_ENDPOINT="https://e1.ai.azure.com/models",
            AZURE_FOUNDRY_1_MODEL="",  # model is blank
        )
        assert s.azure_foundry_backends() == []

    def test_model_without_endpoint_skipped(self):
        s = _settings(
            AZURE_FOUNDRY_1_ENDPOINT="",
            AZURE_FOUNDRY_1_MODEL="m1",
        )
        assert s.azure_foundry_backends() == []

    def test_whitespace_stripped(self):
        s = _settings(
            AZURE_FOUNDRY_1_ENDPOINT="  https://e1.ai.azure.com/models  ",
            AZURE_FOUNDRY_1_MODEL="  grok-4  ",
        )
        backends = s.azure_foundry_backends()
        assert backends[0][0] == "https://e1.ai.azure.com/models"
        assert backends[0][2] == "grok-4"


# ── Factory: build_llm_service ───────────────────────────────────────────────


class TestBuildLlmService:
    def test_unknown_provider_raises(self):
        s = _settings(LLM_PROVIDER="nonexistent")
        from app.llm.factory import build_llm_service

        with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
            build_llm_service(s)

    def test_azure_failover_no_backends_raises(self):
        s = _settings(LLM_PROVIDER="azure_failover")
        from app.llm.factory import build_llm_service

        with pytest.raises(
            ValueError, match="LLM_PROVIDER=azure_failover requires at least"
        ):
            build_llm_service(s)

    def test_azure_failover_one_backend(self):
        s = _settings(
            LLM_PROVIDER="azure_failover",
            AZURE_FOUNDRY_1_ENDPOINT="https://e1.ai.azure.com/models",
            AZURE_FOUNDRY_1_KEY="k1",
            AZURE_FOUNDRY_1_MODEL="m1",
            AZURE_FOUNDRY_API_VERSION="2024-05-01-preview",
        )
        from app.llm.factory import build_llm_service

        svc = build_llm_service(s)
        fp = svc._provider
        from app.llm.providers.failover import FailoverProvider

        assert isinstance(fp, FailoverProvider)
        # Both tiers use the single backend's model
        assert svc._models["fast"] == "m1"
        assert svc._models["quality"] == "m1"
        assert fp.models == ["m1"]

    def test_azure_failover_multiple_backends(self):
        s = _settings(
            LLM_PROVIDER="azure_failover",
            AZURE_FOUNDRY_1_ENDPOINT="https://e1.ai.azure.com/models",
            AZURE_FOUNDRY_1_KEY="k1",
            AZURE_FOUNDRY_1_MODEL="m1",
            AZURE_FOUNDRY_2_ENDPOINT="https://e2.ai.azure.com/models",
            AZURE_FOUNDRY_2_KEY="k2",
            AZURE_FOUNDRY_2_MODEL="m2",
            AZURE_FOUNDRY_3_ENDPOINT="https://e3.ai.azure.com/models",
            AZURE_FOUNDRY_3_KEY="k3",
            AZURE_FOUNDRY_3_MODEL="m3",
        )
        from app.llm.factory import build_llm_service

        svc = build_llm_service(s)
        fp = svc._provider
        from app.llm.providers.failover import FailoverProvider

        assert isinstance(fp, FailoverProvider)
        assert fp.models == ["m1", "m2", "m3"]

    def test_azure_failover_api_version_sets_default_query(self):
        """When api_version is provided, the OpenAICompatibleProvider should
        include it in default_query."""
        s = _settings(
            LLM_PROVIDER="azure_failover",
            AZURE_FOUNDRY_1_ENDPOINT="https://e1.ai.azure.com/models",
            AZURE_FOUNDRY_1_KEY="k1",
            AZURE_FOUNDRY_1_MODEL="m1",
            AZURE_FOUNDRY_API_VERSION="2024-05-01-preview",
        )
        from app.llm.factory import build_llm_service

        svc = build_llm_service(s)
        fp = svc._provider
        p = fp._backends[0].provider
        assert p._client.default_query == {"api-version": "2024-05-01-preview"}

    def test_known_provider_succeeds(self):
        """A plain provider like 'nvidia' builds an OpenAICompatibleProvider."""
        s = _settings(LLM_PROVIDER="nvidia")
        from app.llm.factory import build_llm_service

        svc = build_llm_service(s)
        from app.llm.providers.openai_compatible import OpenAICompatibleProvider

        assert isinstance(svc._provider, OpenAICompatibleProvider)
        assert svc._models["fast"] == s.LLM_MODEL_FAST
        assert svc._models["quality"] == s.LLM_MODEL_QUALITY