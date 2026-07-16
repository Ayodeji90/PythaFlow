"""Central configuration. Everything downstream reads from here, never from the
environment directly, so the app has one typed source of truth."""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- app ---
    ENV: str = "dev"
    APP_VERSION: str = "0.1.0"
    LOG_LEVEL: str = "INFO"

    # --- infra ---
    DATABASE_URL: str = (
        "postgresql+asyncpg://concierge:concierge@localhost:5432/concierge"
    )
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- LLM orchestration (provider-agnostic) ---
    LLM_PROVIDER: str = "nvidia"          # nvidia | openai | groq | mistral | openai_compatible
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = ""                # optional override; blank = provider default
    LLM_MODEL_FAST: str = "meta/llama-3.1-8b-instruct"
    LLM_MODEL_QUALITY: str = "meta/llama-3.3-70b-instruct"
    LLM_TEMPERATURE: float = 0.4
    LLM_MAX_TOKENS: int = 1024

    # --- embeddings (wired in from Day 5) ---
    EMBED_PROVIDER: str = "nvidia"
    EMBED_MODEL: str = "nvidia/nv-embedqa-e5-v5"
    EMBED_DIM: int = 1024

    @field_validator("LLM_API_KEY", "LLM_BASE_URL", "LLM_PROVIDER", mode="before")
    @classmethod
    def _strip(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v


@lru_cache
def get_settings() -> Settings:
    return Settings()
