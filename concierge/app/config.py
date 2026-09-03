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
    LLM_TIMEOUT: float = 60.0   # free-tier 70b can take ~30s to first token

    # --- email channel (optional — only needed when email adapter is used) ---
    EMAIL_SENDER: str = "smtp"          # "smtp" | "sendgrid"
    EMAIL_SMTP_HOST: str = ""
    EMAIL_SMTP_PORT: int = 587
    EMAIL_SMTP_USERNAME: str = ""
    EMAIL_SMTP_PASSWORD: str = ""
    EMAIL_FROM_ADDRESS: str = "concierge@localhost"
    EMAIL_FROM_NAME: str = "Concierge"

    # --- WhatsApp channel (Day 15) --------------------------------------------
    # Twilio is the default because its WhatsApp Sandbox needs NO Meta business
    # verification — a venue (or you) can demo on real WhatsApp with just a Twilio
    # account. Swappable to the Meta Cloud API later (WHATSAPP_PROVIDER=meta).
    WHATSAPP_PROVIDER: str = "twilio"          # twilio | meta (future)
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_WHATSAPP_FROM: str = ""             # e.g. "whatsapp:+14155238886" (sandbox)
    # Verify the X-Twilio-Signature on inbound webhooks (proves it's really Twilio).
    WHATSAPP_VALIDATE_SIGNATURE: bool = True
    # Sandbox fallback: if an inbound message's "To" number matches no whatsapp
    # Channel row, route it to this tenant slug. Blank = strict channel matching.
    WHATSAPP_DEFAULT_TENANT: str = ""
    # Day 16 — hardening.
    # WhatsApp only allows free-form text within 24h of the guest's last message;
    # outside that window a pre-approved template is required.
    WHATSAPP_SESSION_WINDOW_HOURS: int = 24
    WHATSAPP_SEND_MAX_RETRIES: int = 3         # outbound send retries on transient failure
    # Twilio Content template SIDs (HX…) for out-of-window / proactive messages.
    # Submitting + getting these approved is an ops long-lead; blank disables them.
    TWILIO_TEMPLATE_BOOKING_CONFIRMED: str = ""
    TWILIO_TEMPLATE_BOOKING_REMINDER: str = ""

    # --- Telegram MTProto channel ------------------------------------------------
    # MTProto requires API ID and Hash from my.telegram.org, plus a phone number
    # for authentication. Session strings can be stored for persistent connections.
    TELEGRAM_API_ID: int = 0
    TELEGRAM_API_HASH: str = ""
    TELEGRAM_PHONE_NUMBER: str = ""       # e.g. "+2348012345678"
    TELEGRAM_SESSION_STRING: str = ""     # persisted session (optional, for production)
    # Webhook secret for inbound update verification (same pattern as WhatsApp)
    TELEGRAM_WEBHOOK_SECRET: str = ""
    # Webhook URL for receiving updates (if empty, use long polling in dev)
    TELEGRAM_WEBHOOK_URL: str = ""

    # --- guardrails (Day 6) ---
    # Hybrid: rules always run (instant); the LLM moderator only runs on input the
    # rules flag as borderline. Turn the LLM layer off for pure-rules / offline.
    GUARDRAILS_LLM_MODERATION: bool = True
    GUARDRAILS_MODERATION_TIMEOUT: float = 12.0

    # --- LLM orchestration (provider-agnostic) ---
    # nvidia | openai | groq | mistral | openai_compatible | azure_failover
    LLM_PROVIDER: str = "nvidia"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = ""                # optional override; blank = provider default
    LLM_MODEL_FAST: str = "meta/llama-3.1-8b-instruct"
    LLM_MODEL_QUALITY: str = "meta/llama-3.3-70b-instruct"
    LLM_TEMPERATURE: float = 0.4
    LLM_MAX_TOKENS: int = 1024
    # Tier for guest-facing chat replies. Default 'quality' — for a concierge,
    # instruction-following and brand voice matter more than a few hundred ms.
    CHAT_TIER: str = "quality"

    # --- Azure AI Foundry multi-model failover (optional) ---------------------
    # Set LLM_PROVIDER=azure_failover to route across up to 3 Foundry serverless
    # deployments (DeepSeek / Grok / Kimi / …). The router tries backend 1; if it
    # errors OR exceeds AZURE_FOUNDRY_ATTEMPT_TIMEOUT seconds, it falls over to 2,
    # then 3. Order = preference (put your fastest/most reliable model first).
    #
    # If all three are deployments under the SAME Foundry resource, use the SAME
    # endpoint + key for all three and only change the MODEL (the deployment name).
    AZURE_FOUNDRY_1_ENDPOINT: str = ""     # e.g. https://<resource>.services.ai.azure.com/models
    AZURE_FOUNDRY_1_KEY: str = ""
    AZURE_FOUNDRY_1_MODEL: str = ""        # deployment name, e.g. DeepSeek-V4-Pro
    AZURE_FOUNDRY_2_ENDPOINT: str = ""
    AZURE_FOUNDRY_2_KEY: str = ""
    AZURE_FOUNDRY_2_MODEL: str = ""        # e.g. grok-4-20-non-reasoning
    AZURE_FOUNDRY_3_ENDPOINT: str = ""
    AZURE_FOUNDRY_3_KEY: str = ""
    AZURE_FOUNDRY_3_MODEL: str = ""        # e.g. Kimi-K2.6
    # Azure AI Inference endpoints (…/models) require an api-version. Leave blank
    # if your endpoint is a plain OpenAI-compatible route (…/openai/v1).
    AZURE_FOUNDRY_API_VERSION: str = ""
    # Seconds to wait on a backend before routing to the next one.
    AZURE_FOUNDRY_ATTEMPT_TIMEOUT: float = 30.0

    # --- tool calling loop ---
    TOOLS_MAX_STEPS: int = 4

    # --- sheet mirror (pilot booking "system") ---
    SHEET_ID: str = ""
    SHEET_CREDENTIALS_JSON: str = ""  # path to service-account JSON key

    # --- request handling (Day 10) ---
    REQUEST_REVIEW_CONFIDENCE: float = 0.75  # below this => forced human review
    REQUEST_EXTRACTOR_ENABLED: bool = True   # post-turn help classifier
    REQUEST_EXTRACTOR_TIER: str = "fast"
    STAFF_TOKEN_HEADER: str = "X-Staff-Token"  # stopgap auth until Week 3/Day 24

    # --- Staff console (Day 17) -----------------------------------------------
    # Per-tenant staff tokens live at Tenant.config["staff_tokens"]: list[str].
    # In dev environments the literal tenant SUPER_TOKEN below also authenticates
    # every tenant — never set this anywhere non-dev.
    CONSOLE_SUPER_TOKEN: str = "dev-token"
    # Heartbeat the SSE publisher emits to keep EventSource connections open
    # past any idle-timeout in fronting proxies (CloudFront / Nginx).
    CONSOLE_SSE_HEARTBEAT_SECONDS: float = 20.0
    # Max time a single SSE connection stays open. Clients auto-reconnect.
    CONSOLE_SSE_MAX_AGE_SECONDS: int = 600

    # --- embeddings + retrieval (RAG) ---
    EMBED_PROVIDER: str = "nvidia"
    EMBED_MODEL: str = "nvidia/nv-embedqa-e5-v5"
    EMBED_DIM: int = 1024
    # Its own key so the LLM and embeddings can be different vendors (e.g. Groq
    # LLM + NVIDIA embeddings). Blank falls back to LLM_API_KEY (same vendor).
    EMBED_API_KEY: str = ""
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

    def azure_foundry_backends(self) -> list[tuple[str, str, str]]:
        """Return the configured (endpoint, key, model) Foundry backends, in
        preference order. A backend counts as configured once it has both an
        endpoint and a model; blank slots are skipped."""
        raw = [
            (self.AZURE_FOUNDRY_1_ENDPOINT, self.AZURE_FOUNDRY_1_KEY, self.AZURE_FOUNDRY_1_MODEL),
            (self.AZURE_FOUNDRY_2_ENDPOINT, self.AZURE_FOUNDRY_2_KEY, self.AZURE_FOUNDRY_2_MODEL),
            (self.AZURE_FOUNDRY_3_ENDPOINT, self.AZURE_FOUNDRY_3_KEY, self.AZURE_FOUNDRY_3_MODEL),
        ]
        return [
            (e.strip(), k.strip(), m.strip())
            for e, k, m in raw
            if e.strip() and m.strip()
        ]

    @field_validator(
        "LLM_API_KEY", "LLM_BASE_URL", "LLM_PROVIDER", "EMBED_API_KEY", "EMBED_PROVIDER",
        mode="before",
    )
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
        "GUARDRAILS_MODERATION_TIMEOUT",
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
