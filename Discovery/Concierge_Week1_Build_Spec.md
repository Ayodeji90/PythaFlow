# Concierge — Week 1 Build Spec (developer-ready tickets)

*Expands Days 1–7 of [Concierge_30_Day_Sprint.md](./Concierge_30_Day_Sprint.md)
into concrete tickets: exact files, schemas, endpoints, and acceptance criteria.
Hand a day to a developer and they can start.*

---

## Target project structure (new `concierge/` service)

Separate from the SQLite Graycliff demo. Reuses the **LLM provider abstraction
pattern** (`llm_service` + `providers/`), not the demo's data layer.

```
concierge/
  app/
    main.py                    # FastAPI app factory + router mounting + lifespan
    config.py                  # Settings (pydantic-settings, env-driven)
    db.py                      # async SQLAlchemy engine, session, Base
    deps.py                    # FastAPI deps: db session, redis, tenant resolver
    models/
      base.py                  # Base, TimestampMixin, TenantMixin
      tenant.py                # Tenant, User
      channel.py               # Channel
      conversation.py          # Conversation, Message
      guest.py                 # Guest
      reservation.py           # Reservation
      action.py                # Action, Approval
      knowledge.py             # KnowledgeChunk (pgvector)
    schemas/
      message.py               # canonical InboundMessage / OutboundChunk
      chat.py                  # web-chat WS payloads
    orchestrator/
      base.py                  # Orchestrator Protocol
      echo.py                  # Day 3 EchoOrchestrator
      engine.py                # Day 4+ LLM orchestrator
      state.py                 # conversation state (Redis hot + DB history)
      guardrails.py            # Day 6 guardrail checks
    llm/
      service.py               # LLMService interface + factory (ported)
      providers/anthropic_provider.py
      providers/openai_provider.py
      embeddings.py            # EmbeddingService interface + provider
    knowledge/
      ingest.py                # chunk + embed + upsert
      retrieve.py              # vector search
    channels/
      base.py                  # ChannelAdapter interface
      webchat.py               # WebSocket adapter (Week 1)
    routers/
      health.py
      webchat.py               # WS /ws/chat + POST /api/chat
      knowledge.py             # POST /api/kb ingest (Day 5)
    logging.py                 # structured logging + PII redaction (Day 6)
  alembic/ (env.py, versions/)
  scripts/ (seed.py, check_llm.py, ingest_kb.py)
  tests/ (conftest.py, test_*.py, eval/)
  docker-compose.yml  Dockerfile  alembic.ini  pyproject.toml  .env.example
```

**Stack:** Python 3.12 · FastAPI · SQLAlchemy 2.0 (async, `asyncpg`) · Alembic ·
Postgres 16 + **pgvector** · Redis 7 · pydantic v2 + pydantic-settings · uvicorn.
Package/venv via `uv` (or poetry). Lint: `ruff`. Tests: `pytest` + `pytest-asyncio`.

---

# Day 1 — Project skeleton + long-lead kickoff

**Objective:** the service runs locally; external approval clocks start.

### W1-D1-1 · Repo scaffold & tooling
- **Files:** `concierge/pyproject.toml`, `ruff.toml`, `.gitignore`, `README.md`,
  `.env.example`, `SPRINT_LOG.md`
- **Detail:** deps as above; `ruff` + `pytest` configured; `.env.example` lists
  every key (below).
- **Done:** `uv sync` installs; `ruff check` passes on an empty app.

### W1-D1-2 · Config
- **Files:** `app/config.py`
- **Detail:** `Settings(BaseSettings)` with:
  `DATABASE_URL, REDIS_URL, LLM_PROVIDER, ANTHROPIC_API_KEY, OPENAI_API_KEY,
  LLM_MODEL_FAST, LLM_MODEL_QUALITY, EMBED_PROVIDER, EMBED_MODEL, EMBED_DIM,
  ENV, LOG_LEVEL, APP_VERSION`. Cached `get_settings()`.
- **Done:** `get_settings()` loads from `.env`; missing required keys fail loudly.

### W1-D1-3 · DB + Redis wiring
- **Files:** `app/db.py`, `app/deps.py`, `app/services/redis.py`
- **Detail:** async engine from `DATABASE_URL`; `async_sessionmaker`; declarative
  `Base`; `get_db()` and `get_redis()` FastAPI deps.
- **Done:** app opens a DB session and pings Redis at startup (lifespan) without error.

### W1-D1-4 · App factory + health endpoint
- **Files:** `app/main.py`, `app/routers/health.py`
- **Endpoint:** `GET /health` → `{"status":"ok","db":true,"redis":true,"version":APP_VERSION}`
  (actually checks a `SELECT 1` and a Redis `PING`).
- **Done:** `GET /health` returns 200 with all-true.

### W1-D1-5 · Local infra (docker-compose)
- **Files:** `docker-compose.yml`, `Dockerfile`
- **Detail:** services — `db` (`pgvector/pgvector:pg16`), `redis:7`, `api`
  (this app). Volume for pg data. `CREATE EXTENSION vector` on init.
- **Done:** `docker compose up` boots all three; `GET /health` → 200 from the container.

### W1-D1-6 · LLM key smoke test
- **Files:** `scripts/check_llm.py`
- **Done:** running it returns a completion from the configured provider.

### W1-D1-7 · Long-lead OPS tickets (no code — start today)
- **Done:** Meta Business verification **submitted**; WhatsApp **BSP account
  requested** (360dialog/Twilio); pilot venue confirmed; hosting region chosen;
  30-day tickets in the tracker.

> **Maps to Day 1 checklist:** compose up + `/health` 200 · pg+redis+pgvector
> reachable · Meta submitted/BSP requested · LLM key works · tickets created.

---

# Day 2 — Data model & multi-tenancy

**Objective:** every row belongs to a tenant; migrations apply from scratch.

### W1-D2-1 · Base mixins
- **Files:** `app/models/base.py`
- **Detail:** `Base`; `TimestampMixin(created_at, updated_at)`;
  `TenantMixin(tenant_id: UUID FK->tenants.id, indexed)`. UUID PKs everywhere.

### W1-D2-2 · Core models
- **Files:** `app/models/{tenant,channel,conversation,guest,reservation,action,knowledge}.py`
- **Schemas (columns):**
  - **Tenant:** `id, slug(unique), name, brand_voice(text), languages(jsonb),
    timezone, hours(jsonb), config(jsonb), created_at, updated_at`
  - **User:** `id, tenant_id, email, name, role(enum: owner|manager|staff),
    auth_ref, created_at` (unique `(tenant_id,email)`)
  - **Channel:** `id, tenant_id, type(enum: webchat|whatsapp|sms|voice|instagram|
    email), external_id, config(jsonb), active(bool)`
  - **Guest:** `id, tenant_id, display_name, phone, handles(jsonb),
    preferences(jsonb), consent(jsonb), created_at, last_seen_at`
  - **Conversation:** `id, tenant_id, guest_id?, channel_id, channel_type,
    external_thread_id, language, status(enum: active|human|closed), state(jsonb),
    created_at, updated_at` (index `(tenant_id, external_thread_id)`)
  - **Message:** `id, tenant_id, conversation_id, role(enum: guest|assistant|
    staff|system|tool), content(text), content_type(default 'text'), meta(jsonb),
    created_at` (index `(conversation_id, created_at)`)
  - **Reservation:** `id, tenant_id, guest_id?, conversation_id?, party_size,
    date, time, area, notes, status(enum: pending|approved|confirmed|cancelled|
    rejected), source_channel, external_ref, idempotency_key(unique), created_at,
    updated_at`
  - **Action:** `id, tenant_id, conversation_id, type(str tool name), input(jsonb),
    output(jsonb), status(enum: proposed|executed|failed), created_at`
  - **Approval:** `id, tenant_id, action_id?, reservation_id?, status(enum:
    pending|approved|rejected), decided_by(user?), decided_at, created_at`
  - **KnowledgeChunk:** `id, tenant_id, source, title, content(text),
    embedding(Vector(settings.EMBED_DIM)), meta(jsonb), created_at`
- **Note:** `EMBED_DIM` is provider-driven (OpenAI `text-embedding-3-small`=1536;
  Voyage `voyage-3`=1024). Changing provider ⇒ re-embed + migration.

### W1-D2-3 · Alembic + first migration
- **Files:** `alembic.ini`, `alembic/env.py`, `alembic/versions/0001_init.py`
- **Detail:** async env; migration includes `CREATE EXTENSION IF NOT EXISTS vector`
  and an `ivfflat`/`hnsw` index on `knowledge_chunks.embedding`.
- **Done:** `alembic upgrade head` builds the whole schema on an empty DB.

### W1-D2-4 · Seed script
- **Files:** `scripts/seed.py`
- **Done:** creates one Tenant + one staff User + a webchat Channel.

### W1-D2-5 · Tenant isolation test
- **Files:** `tests/test_models.py`
- **Done:** a query filtered by `tenant_id` returns only that tenant's rows; ERD
  committed (`docs/erd.md` or an image).

> **Maps to Day 2 checklist:** migrations clean · seed works · isolation proven · ERD committed.

---

# Day 3 — Canonical Message + orchestrator skeleton + web-chat echo

**Objective:** a message round-trips and is persisted.

### W1-D3-1 · Canonical message schema
- **Files:** `app/schemas/message.py`
- **Detail:**
  ```python
  class SenderRef(BaseModel): id: str; name: str|None=None; phone: str|None=None; handle: str|None=None
  class InboundMessage(BaseModel):
      tenant_slug: str; channel: ChannelType; conversation_ref: str
      sender: SenderRef; content: str; content_type: Literal["text","audio"]="text"
      locale: str|None=None; received_at: datetime; metadata: dict={}
  class OutboundChunk(BaseModel):
      type: Literal["token","message","typing","action","done","error"]
      content: str|None=None; metadata: dict={}
  ```

### W1-D3-2 · Orchestrator interface + Echo impl
- **Files:** `app/orchestrator/base.py`, `app/orchestrator/echo.py`
- **Detail:**
  ```python
  class Orchestrator(Protocol):
      async def handle(self, msg: InboundMessage, db, redis) -> AsyncIterator[OutboundChunk]: ...
  ```
  `EchoOrchestrator` yields a `message` chunk echoing input, then `done`.

### W1-D3-3 · Channel adapter base + webchat WS
- **Files:** `app/channels/base.py`, `app/channels/webchat.py`, `app/routers/webchat.py`
- **Endpoints:**
  - `WS /ws/chat?tenant=<slug>&conversation=<ref>` — client sends
    `{"content": "..."}`; server streams `OutboundChunk` JSON frames.
  - `POST /api/chat` `{tenant, conversation_ref, content}` → non-streaming
    `{reply}` (test/fallback path).
- **Detail:** adapter resolves/creates Conversation + Guest, builds `InboundMessage`,
  calls the orchestrator, persists inbound + outbound `Message` rows.

### W1-D3-4 · Persistence + test
- **Files:** `tests/test_webchat_echo.py`
- **Done:** WS echo works; both messages persisted under the right tenant/conversation.

> **Maps to Day 3 checklist:** echo round-trips · persisted correctly · schema documented.

---

# Day 4 — LLM in the loop (streaming, stateful, ungrounded)

**Objective:** coherent, in-persona, multi-turn replies that stream.

### W1-D4-1 · Port the LLM abstraction
- **Files:** `app/llm/service.py`, `app/llm/providers/{anthropic,openai}_provider.py`
- **Detail:** port the Graycliff `llm_service` interface + provider factory. Add a
  **streaming** method:
  ```python
  class LLMService(Protocol):
      async def generate(self, messages: list[LLMMessage], *, tier: Literal["fast","quality"], system: str) -> str: ...
      async def stream(self, messages, *, tier, system) -> AsyncIterator[str]: ...
  ```

### W1-D4-2 · Conversation state
- **Files:** `app/orchestrator/state.py`
- **Detail:** load recent `Message` history from DB; keep hot state in Redis
  (`conv:{id}` → rolling window); context-window trimming/summarization hook.

### W1-D4-3 · LLM orchestrator
- **Files:** `app/orchestrator/engine.py`
- **Detail:** build system prompt from `Tenant.brand_voice` + hours/policies;
  assemble history + new turn; `stream()` tokens out as `OutboundChunk(type="token")`,
  then persist the full assistant `Message` and emit `done`.
- **Wire:** webchat router uses `LLMOrchestrator` instead of `EchoOrchestrator`.

### W1-D4-4 · Test
- **Files:** `tests/test_orchestrator_llm.py` (mock LLM provider)
- **Done:** coherent in-persona reply · multi-turn references prior turn · tokens stream.

> **Maps to Day 4 checklist:** coherent persona reply · multi-turn context · streaming.

---

# Day 5 — Knowledge base + RAG (grounded answers)

**Objective:** answers come from the venue's real facts.

### W1-D5-1 · Embeddings service
- **Files:** `app/llm/embeddings.py`
- **Detail:**
  ```python
  class EmbeddingService(Protocol):
      async def embed(self, texts: list[str]) -> list[list[float]]: ...
  ```
  Provider chosen by `EMBED_PROVIDER`; dim = `EMBED_DIM`.

### W1-D5-2 · Ingestion pipeline
- **Files:** `app/knowledge/ingest.py`, `scripts/ingest_kb.py`, `app/routers/knowledge.py`
- **Endpoint:** `POST /api/kb` `{tenant, source, title, text}` → chunk → embed →
  upsert `KnowledgeChunk[]`. Chunking: ~500–800 tokens, overlap ~80.
- **Done:** ingest one venue's hours/menu/policies; chunks + embeddings stored.

### W1-D5-3 · Retrieval
- **Files:** `app/knowledge/retrieve.py`
- **Detail:** `retrieve(tenant_id, query, k=6)` → pgvector cosine search
  (`embedding <=> :q` with the vector index), tenant-scoped.
- **Done:** returns relevant chunks for a query (spot-checked).

### W1-D5-4 · Ground the orchestrator
- **Files:** `app/orchestrator/engine.py` (update)
- **Detail:** retrieve top-k, inject as context with source tags; instruct "answer
  only from provided context; if absent, say you'll get a human."
- **Done:** "hours?" / "vegan options?" → grounded answer · unknown → safe "I don't
  have that" (no hallucination).

> **Maps to Day 5 checklist:** grounded answers · relevant retrieval · no invention on unknowns.

---

# Day 6 — Guardrails v1 + grounding discipline

**Objective:** it won't lie or wander; PII is protected.

### W1-D6-1 · Guardrail module
- **Files:** `app/orchestrator/guardrails.py`
- **Detail:** **pre-checks** (scope/abuse/PII on input, language) and
  **post-checks** (claim not grounded in retrieved context/tool output → downgrade
  to "let me check with the team"; block writes without confirmation). Returns
  `Allow | Rewrite | Refuse | Escalate`.

### W1-D6-2 · Wire into engine + low-confidence escalation
- **Files:** `app/orchestrator/engine.py` (update)
- **Detail:** run pre-checks before LLM, post-checks before emitting; set
  `Conversation.status="human"` + emit an `escalate` action on `Escalate`.

### W1-D6-3 · PII-safe logging
- **Files:** `app/logging.py`
- **Detail:** structured logs; redact phone/email/card patterns; never log raw KB
  secrets.
- **Done:** logs show redacted PII.

### W1-D6-4 · Guardrail test set
- **Files:** `tests/test_guardrails.py`
- **Done:** adversarial prompts (invent a price, off-topic, injection) → safe
  deflection; a scripted set passes.

> **Maps to Day 6 checklist:** adversarial → safe · PII redacted · guardrail tests pass.

---

# Day 7 — Review · demo · buffer

**Objective:** a real grounded web-chat concierge exists and is green.

### W1-D7-1 · End-to-end demo script
- **Files:** `docs/demo_week1.md` (+ optional recording)
- **Done:** scripted demo — grounded Q&A + a safe refusal — recorded for one venue.

### W1-D7-2 · Test + CI green
- **Files:** `.github/workflows/ci.yml`
- **Done:** `pytest` + `ruff` pass in CI; coverage on models/orchestrator/guardrails.

### W1-D7-3 · Groom + status
- **Done:** Meta verification status checked; Week 2 backlog (tool-calling,
  reservations, approvals) groomed; `SPRINT_LOG.md` updated.

> **Maps to Day 7 checklist:** demo recorded · suite green · verification checked · backlog groomed.

---

## `.env.example` (Day 1 deliverable)

```
ENV=dev
APP_VERSION=0.1.0
LOG_LEVEL=INFO
DATABASE_URL=postgresql+asyncpg://concierge:concierge@db:5432/concierge
REDIS_URL=redis://redis:6379/0
LLM_PROVIDER=anthropic            # anthropic | openai
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
LLM_MODEL_FAST=claude-haiku-4-5-20251001
LLM_MODEL_QUALITY=claude-opus-4-8
EMBED_PROVIDER=openai             # openai | voyage
EMBED_MODEL=text-embedding-3-small
EMBED_DIM=1536
```

## What Week 1 deliberately excludes (comes later)
- Tool-calling / reservations / approvals → **Week 2** (Days 8–11)
- WhatsApp adapter → **Week 3** (Day 15) — proves the design when it needs *zero*
  brain changes
- Staff console UI → **Week 3** (Days 17–20)
- Voice → **Phase 1** (next sprint)
