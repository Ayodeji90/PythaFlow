# Sprint Log — PythaFlow Concierge (Phase 0)

## Day 1 — Project skeleton + long-lead kickoff
- Scaffolded `concierge/` service (FastAPI · async SQLAlchemy · Postgres+pgvector · Redis), uv-managed.
- `config.py` Settings; `/health` checks a real DB `SELECT 1` + Redis `PING`.
- docker-compose: `pgvector/pgvector:pg16` + `redis:7` + api; `CREATE EXTENSION vector` on init.
- LLM seam built provider-agnostic: app core → `LLMService` → provider wrapper → vendor API.
  Default provider **NVIDIA NIM** (OpenAI-compatible); `scripts/check_llm.py` smoke test.
- **OPS (owner):** submit Meta Business verification · request WhatsApp BSP · seed 30-day tracker.

**Verified ✅ (Day 1 DONE):** `docker compose up --build` boots api+db+redis;
`GET /health` → 200 `{"status":"ok","db":true,"redis":true,"version":"0.1.0"}`;
`vector` extension present; `ruff` clean; imports OK;
**`check_llm.py` → `✓ nvidia replied`** (NVIDIA NIM live end-to-end).

Notes:
- Fixed a `.env` footgun: inline comments on value lines were parsed as the value
  (broke the key). Comments now on their own lines + a `_strip` validator in config.
- Local DNS couldn't resolve `integrate.api.nvidia.com` (systemd-resolved); fixed
  on the dev machine via resolver flush / public DNS.
- Small free model (llama-3.1-8b) follows instructions loosely — use the
  `quality` tier + guardrails (Day 6) where precision matters.

_Owner tasks (long-lead, not blocking Day 2):_ Meta Business verification,
WhatsApp BSP, seed the 30-day tracker.

### Day 1 — hardening pass (CodeRabbit review)
Applied the valid findings from the CodeRabbit review of the Day-1 commit:
- **Timeouts everywhere:** bounded DB connect + health probe (`asyncio.wait_for`),
  Redis `socket_connect_timeout`/`socket_timeout`, and an `AsyncOpenAI` request
  timeout (`LLM_TIMEOUT`) threaded through the factory. A slow/unreachable
  dependency can no longer hang startup, `/health`, or a request.
- **`/health` returns 503 when degraded** (was 200) — correct readiness semantics.
- **Config safety:** bound-check validators (temperature 0–2, positive tokens/dim/
  timeouts) + a **fail-closed** guard that refuses to boot a non-dev `ENV` on the
  throwaway `concierge:concierge` / default Redis.
- **Small:** `check_llm.py` constructs the service inside `try`; `docker-compose`
  `.env` is now `required: false`; doc uses `docker compose exec`.
- **Hygiene:** `graphify-out/` gitignored + untracked (it embedded machine paths).
- Dismissed one finding (dotenv inline-comment claim) — **verified** our parser
  loads the comment as the value, so the Day-1 doc was correct.

Verified: `/health` 200↔503, `check_llm` → PONG, `pytest` 2 passed, `ruff` clean.

## Day 2 — Data model & multi-tenancy
- 10 SQLAlchemy models (`Tenant, User, Channel, Guest, Conversation, Message,
  Reservation, Action, Approval, KnowledgeChunk`) with UUID PKs, `TenantMixin`
  (`tenant_id` on every domain table), timestamps, and VARCHAR-backed enums.
- Alembic wired for **async** migrations; URL + metadata pulled from app Settings.
  First migration `78bc7232c288` creates the `vector` extension, all tables, and
  the **HNSW** cosine index on `knowledge_chunks.embedding` (1024-dim).
- `scripts/seed.py` (idempotent): demo tenant + owner + webchat channel.
- ERD committed at `docs/erd.md` (Mermaid).

**Verified ✅ (Day 2 DONE):**
- `docker compose down -v` → `alembic upgrade head` builds the whole schema from
  scratch; 10 tables + `ix_knowledge_chunks_embedding` (HNSW) present.
- `seed.py` creates rows; re-run is a no-op (idempotent).
- `pytest` → 2 passed (tenant isolation + defaults/PK).
- `alembic check` → **no drift** (migration matches models exactly).
- `ruff` clean (alembic/ excluded as generated code).

Notes / decisions:
- Enums as `VARCHAR + CHECK` (`native_enum=False`) so adding a status later is a
  light migration, not an `ALTER TYPE`.
- `Reservation` has a unique `(tenant_id, idempotency_key)` → double-booking is
  structurally impossible on tool retries.
- pgvector HNSW index is raw SQL in the migration + filtered from autogenerate via
  `include_object` in `alembic/env.py` (access methods don't round-trip).
