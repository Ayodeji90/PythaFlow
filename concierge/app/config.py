"""Central configuration. Everything downstream reads from here, never from the
environment directly, so the app has one typed source of truth."""
from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The committed dev defaults — throwaway credentials that must never be used
# outside a development/test environment (see the fail-closed guard below).
_DEV_DB_DEFAULT = "postgresql+asyncpg://concierge:concierge@localhost:5432/concierge"
_DEV_REDIS_DEFAULT = "redis://localhost:6379/0"
_DEV_ENVS = {"dev", "development", "local", "test"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- app ---
    ENV: str = "dev"
    APP_VERSION: str = "0.1.0"
    LOG_LEVEL: str = "INFO"

    # --- infra ---
    DATABASE_URL: str = _DEV_DB_DEFAULT
    REDIS_URL: str = _DEV_REDIS_DEFAULT

    # --- timeouts (seconds) — keep a slow/unreachable dependency from hanging
    #     startup, health checks, or request work ---
    DB_CONNECT_TIMEOUT: float = 5.0
    HEALTH_PROBE_TIMEOUT: float = 3.0
    REDIS_CONNECT_TIMEOUT: float = 3.0
    REDIS_SOCKET_TIMEOUT: float = 3.0
    LLM_TIMEOUT: float = 30.0

    # --- LLM orchestration (provider-agnostic) ---
    LLM_PROVIDER: str = "nvidia"          # nvidia | openai | groq | mistral | openai_compatible
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = ""                # optional override; blank = provider default
    LLM_MODEL_FAST: str = "meta/llama-3.1-8b-instruct"
    LLM_MODEL_QUALITY: str = "meta/llama-3.3-70b-instruct"
    LLM_TEMPERATURE: float = 0.4
    LLM_MAX_TOKENS: int = 1024
    # Tier for guest-facing chat replies. Default 'quality' — for a concierge,
    # instruction-following and brand voice matter more than a few hundred ms.
    CHAT_TIER: str = "quality"

    # --- embeddings + retrieval (RAG) ---
    EMBED_PROVIDER: str = "nvidia"
    EMBED_MODEL: str = "nvidia/nv-embedqa-e5-v5"
    EMBED_DIM: int = 1024
    RAG_TOP_K: int = 6
    # Cosine-distance floor for pgvector's `<=>` (0 = identical … 2 = opposite).
    # A chunk further than this is treated as "not relevant" → no context is
    # injected and the concierge says it'll check with the team, rather than
    # answering from a bad match.
    #
    # Calibrated against nv-embedqa-e5-v5 on real venue Q&A: genuine matches land
    # ~0.54–0.65, genuine misses ~0.72+, so 0.68 sits cleanly in the gap. Retune
    # per embedding model / venue if that distribution shifts.
    RAG_MAX_DISTANCE: float = 0.68

    @field_validator("LLM_API_KEY", "LLM_BASE_URL", "LLM_PROVIDER", mode="before")
    @classmethod
    def _strip(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v

    @field_validator("LLM_TEMPERATURE")
    @classmethod
    def _check_temperature(cls, v: float) -> float:
        if not 0.0 <= v <= 2.0:
            raise ValueError("LLM_TEMPERATURE must be between 0.0 and 2.0")
        return v

    @field_validator(
        "LLM_MAX_TOKENS",
        "EMBED_DIM",
        "RAG_TOP_K",
        "DB_CONNECT_TIMEOUT",
        "HEALTH_PROBE_TIMEOUT",
        "REDIS_CONNECT_TIMEOUT",
        "REDIS_SOCKET_TIMEOUT",
        "LLM_TIMEOUT",
    )
    @classmethod
    def _check_positive(cls, v: float, info) -> float:
        if v <= 0:
            raise ValueError(f"{info.field_name} must be greater than 0")
        return v

    @model_validator(mode="after")
    def _fail_closed_outside_dev(self) -> "Settings":
        """Refuse to boot a non-dev environment on the committed throwaway
        credentials — surfaces a misconfigured deploy immediately instead of
        silently running on `concierge:concierge` / unauthenticated Redis."""
        if self.ENV.lower() not in _DEV_ENVS:
            problems = []
            if self.DATABASE_URL == _DEV_DB_DEFAULT or "concierge:concierge@" in self.DATABASE_URL:
                problems.append("DATABASE_URL still uses the dev default / throwaway credentials")
            if self.REDIS_URL == _DEV_REDIS_DEFAULT:
                problems.append("REDIS_URL still uses the dev default")
            if problems:
                raise ValueError(
                    f"ENV={self.ENV!r} requires real infrastructure settings: "
                    + "; ".join(problems)
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
