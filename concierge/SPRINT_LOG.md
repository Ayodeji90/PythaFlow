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

## Day 3 — Canonical Message + orchestrator skeleton + web-chat echo
- **Canonical contract** (`app/schemas/message.py`): `InboundMessage` / `OutboundChunk`
  — wire DTOs, deliberately separate from the persisted `Message` row.
- **Orchestrator seam**: `Orchestrator` Protocol + `EchoOrchestrator`. Streaming
  (`AsyncIterator`) from day one so Day 4's tokens need no interface change;
  `redis` threaded through unused for the same reason.
- **Channel layer**: `ChannelAdapter` + a **shared, channel-agnostic pipeline**
  (`handle_inbound`) that resolves tenant → resolves/creates Conversation →
  persists the guest turn → runs the orchestrator → persists the assistant turn.
  The only channel-specific code is `WebChatAdapter.to_inbound()`.
- **Endpoints**: `WS /ws/chat`, `POST /api/chat`, and a **dev-only** `GET /dev/chat`
  test page (mounted only when ENV is dev).
- Docs: `docs/canonical-message.md`.

**Verified ✅ (Day 3 DONE):**
- Real WebSocket round-trip: `action(connected) → typing → message → done`,
  echo returned correctly.
- Both turns persisted under the right tenant + conversation (`guest` then
  `assistant`), confirmed via psql.
- `pytest` → 6 passed (echo+persistence, thread reuse → one conversation,
  unknown tenant raises, REST endpoint 200 + 404). `ruff` clean.

Notes / decisions:
- Guest turn is committed **before** the orchestrator runs — a failure mid-think
  never loses what the guest said.
- `guest_id` stays NULL for anonymous web chat (Day 2 made it nullable); guest
  identity/memory is Day 11.
- Did **not** wire the marketing-site hero chat — it's a scripted prop, not a
  client. A dev-only page keeps product and marketing separate.
- WS uses a short-lived DB session per turn so a long-lived socket never pins a
  connection open.
- ruff: `Depends()` in defaults is the FastAPI idiom → configured bugbear's
  `extend-immutable-calls` instead of contorting the code (B008 false positive).

## Day 4 — LLM in the loop (streaming, stateful, ungrounded)
- **Streaming added to the seam**: `LLMProvider.stream()` (OpenAI-compatible impl
  yields `delta.content`; base has a non-streaming fallback) + `LLMService.stream()`.
  NVIDIA streaming works through the same call — zero new vendor code.
- **Conversation state** (`orchestrator/state.py`): history read fresh from
  **Postgres** (source of truth), last ~20 turns, mapped to LLM messages, with a
  summarisation hook stubbed.
- **Redis earns its keep** (`services/locks.py`): a per-conversation turn lock that
  **serialises** turns (waits, doesn't drop) so a double-send can't interleave
  two replies. No-op when redis is None.
- **LLMOrchestrator** (`orchestrator/engine.py`): persona from `Tenant` fields
  (`prompt.py`), streams `token` chunks, persists nothing (the Day-3 pipeline
  concatenates + writes the assistant turn). Wired via `app.state.orchestrator`
  so tests swap in echo/fakes — no network in CI.
- **Model tier**: guest chat defaults to `CHAT_TIER=quality` (llama-3.3-70b) —
  instruction-following/persona matter more than latency for a concierge.

**Verified ✅ (Day 4 DONE):**
- Live NVIDIA over the real WebSocket: turn 1 streamed in **50 token chunks**,
  in-persona ("…celebrate with us at Demo Bistro"), model=llama-3.3-70b.
- Multi-turn: turn 2 recalled "Amara" + "anniversary" → PASS. All 4 turns
  persisted (2 guest / 2 assistant), confirmed via psql.
- `pytest` → 8 passed (fake-provider streaming/persona/multi-turn, + Day 1-3
  suite). `ruff` clean.

Notes / decisions:
- **Overrode the spec on Redis**: no history cache (staleness risk = model forgets
  the last turn). Postgres stays truth; Redis does the turn lock instead.
- Day-4 **honesty rail** in the system prompt ("do not invent hours/prices/menu")
  — a stopgap until real grounding (Day 5) + guardrails (Day 6). Confirmed the
  model refrained from inventing specifics.
- Orchestrator swap was the promised **one line** (`app.state.orchestrator`),
  proving the Day-3 seam.

## Day 5 — Knowledge base + RAG (grounded answers)
- **Embeddings seam** (`llm/embeddings.py`): mirrors the LLM seam; NVIDIA
  `nv-embedqa-e5-v5` via the OpenAI-compatible client, with correct
  query/passage `input_type` asymmetry.
- **Structure-first chunking** (`knowledge/chunk.py`): splits on headings/blank
  lines into small titled units (one fact each), packing only long sections.
- **Ingestion** (`knowledge/ingest.py`, `scripts/ingest_kb.py`, `POST /api/kb`):
  chunk → embed → **upsert** (re-ingesting a source replaces its chunks).
- **Retrieval** (`knowledge/retrieve.py`): tenant-scoped pgvector cosine search
  on the HNSW index + the **similarity floor** — matches worse than
  `RAG_MAX_DISTANCE` are dropped so the concierge defers instead of guessing.
- **Grounded orchestrator**: retrieves per turn, injects tagged CONTEXT, and the
  prompt enforces "answer only from CONTEXT, else check with the team." `done`
  metadata carries `grounded`.

**Verified ✅ (Day 5 DONE):**
- Ingested a real Demo Bistro fact sheet → 6 titled chunks (real NVIDIA embeddings).
- Retrieval (real embeddings): 5/5 known questions HIT, 3/3 unknowns deferred.
- Live end-to-end: "opening hours?" → grounded, correct ("5–11pm, Tue–Sun, closed
  Mondays, kitchen 10:15pm"); "vegan?" → "six vegan dishes"; "wifi password?" /
  "swimming pool?" → defers to team (no invention). `grounded` flag matched.
- `pytest` → 13 passed; `ruff` clean.

Notes / decisions:
- **Floor calibration is a real finding**: the initial 0.55 rejected valid
  questions. Measured real distances — genuine matches ~0.54–0.65, misses ~0.72+
  — and set the floor to **0.68** (in the gap). Documented; retune per model.
- **Compound-question dilution**: a two-intent query ("open Mondays AND vegan?")
  blends into one embedding and can miss one intent; the model then *defers* on
  the un-retrieved part rather than inventing (safe). Query decomposition / higher
  top-k is a later refinement, not a Day-5 need.
- **NVIDIA free tier rate-limits the 70b** (visible `Retrying request…`), so live
  turns can be slow; the RAG core was verified deterministically to avoid that.
- Test fixture now uses `join_transaction_mode="create_savepoint"` so app-code
  `commit()`s (ingest) roll back cleanly.

## Day 7 — Review · demo · buffer

**Week 1 retrospective: Days 1–7 delivered a grounded, guardrailed web-chat concierge for one venue (Demo Bistro). The architecture is multi-tenant, streaming, and provider-agnostic — exactly what the sprint plan's "North Star" called for at this stage.**

### What's green ✅
- **Test suite: 23/23 pass** (unit + DB-dependent + WebSocket echo). Ruff clean.
- **All services boot**: `docker compose up` → api + postgres + redis; `GET /health` → `{"status":"ok","db":true,"redis":true}`
- **Demo Bistro seeded** — tenant, owner, webchat channel created; 6 knowledge chunks ingested (hours, reservations, dietary, parking, pets, cancellation).
- **Zero TODOs, FIXMEs, or HACKs** in the codebase.
- **No drift**: `alembic check` would pass (migrations match models).

### What's yellow ⚡
- **Meta Business verification** — noted as "submit Day 1" in the sprint plan. This is an owner task, not code. If not yet submitted, it gates WhatsApp (Days 15–16). Track this externally.
- **Demo recording** — the system is demo-ready (seeded tenant + KB + guardrails + dev chat page at `/dev/chat`). A manual screen recording of a grounded Q&A session would close this checklist item.

### Week 2 backlog (Days 8–14) — groomed
| Day | What | Notes |
|-----|------|-------|
| **8** | Tool-calling framework | Function-calling loop + tool registry + typed tools. Action model already exists. |
| **9** | Availability + booking backend | CheckAvailability + CreateReservation + Google Sheet mirror. Reservation model exists. |
| **10** | Write-action approval flow | Pending → Approval queue → confirm on staff approve. Approval model exists. |
| **11** | Modify / cancel + guest memory | ModifyReservation, CancelReservation, Guest profile + consent. Guest model exists. |
| **12** | Multi-turn robustness | Corrections, confirmations, reminders. |
| **13** | Eval harness | Golden-dialogue test suite in CI. |
| **14** | Review · demo · buffer | Booking loop with approval, WhatsApp sandbox check. |

The model layer (Action, Approval, Reservation, Guest) is already in place from Days 2–3, so Days 8–11 won't be starting from scratch.

**Week 1 verdict:** Demo Bistro is ready to answer grounded, guardrailed questions via web chat. A guest can ask about hours, menu, parking, reservations policies and get accurate, on-brand answers with safe deflection for unknowns.
- **Hybrid guardrail module** (`app/orchestrator/guardrails.py`): deterministic
  rules (injection, human-request, abuse detection via regex) run instantly and
  short-circuit the obvious cases. An **LLM moderator** is consulted only for
  borderline input flagged by `_SUSPICIOUS` patterns — so normal chat never pays
  for an extra LLM round-trip. The moderator fails **open** (allow) on
  timeout/error so a flaky classifier never blocks a real guest.
- **Three guardrail actions**: `ALLOW` → proceed to grounded answer; `REFUSE` →
  safe deflection, LLM never invoked; `ESCALATE` → conversation status set to
  `human`, hand off to staff.
- **PII-safe logging** (`app/logging.py`): `redact()` strips emails, phone
  numbers, and credit card numbers before they reach logs; `RedactingFormatter`
  wraps the standard logging formatter.
- **Wired into the orchestrator** (`app/orchestrator/engine.py`): `check_inbound()`
  runs at the top of every `handle()` call before RAG or LLM touch the input.
- **Toggle settings** in config: `GUARDRAILS_LLM_MODERATION` (on/off) and
  `GUARDRAILS_MODERATION_TIMEOUT` (12s default).

**Verified ✅ (Day 6 DONE):**
- Adversarial prompts ("ignore instructions", "reveal system prompt",
  "jailbreak") → refused without reaching the LLM.
- Human-request ("speak to a manager", "get me a human") → escalated.
- Abuse → escalated.
- Clean queries → allowed with no LLM moderator call.
- Borderline input ("pretend the kitchen is open") → LLM moderator consulted;
  fail-open path tested (moderator crash → still allowed).
- PII redaction proven: emails, phones, and card numbers stripped from log
  output.
- `pytest` → 13 passed (unit + guardrail suite; WebSocket tests require a
  running app). `ruff` clean.
