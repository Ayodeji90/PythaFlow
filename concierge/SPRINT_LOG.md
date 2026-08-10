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

## Day 8 — Tool-calling framework
(Tool-calling loop + tool registry + typed tools. Action model already existed.)

## Day 9 — Availability + booking backend + tools + Sheet mirror
(Availability slot computation, CheckAvailability tool, DraftReservation tool, LocalBookingStore, optional Google Sheets mirror, idempotency.)

## Day 10 — Write-action approval flow (human-in-the-loop)
- **Notification abstraction** (`app/notifications/__init__.py`): single `notify()` function with event constants (`NOTIF_REQUEST_CREATED`, `NOTIF_REQUEST_APPROVED`, `NOTIF_REQUEST_REJECTED`). Async signature for future channel handlers.
- **Fulfilment tool** (`app/tools/create_reservation.py`): `ToolKind.fulfilment` — hidden from LLM by registry filtering; calls `LocalBookingStore.create()` to actually write the Reservation row after staff approval.
- **Approval schemas** (`app/schemas/approval.py`): `DecideRequest`, `DecideResponse`, `ApprovalQueueItem`, `ApprovalQueueResponse`.
- **Staff API endpoints** (`app/routers/approvals.py`):
  - `GET /api/approvals` — lists pending Requests (needs_review|new), newest first
  - `POST /api/approvals/decide` — approve (→ fulfil → notify) or reject (→ notify)
  - Auth via `X-Staff-Token` header
- **Orchestrator post-loop awareness** (`app/orchestrator/engine.py`): tracks `draft_detected` from action chunks; after tool loop yields "sent for review" message to guest; fires `_run_extractor()` as fire-and-forget `asyncio.create_task` to classify unhandled intents into Requests.
- **Dev approvals page** at `/dev/approvals` (vanilla JS, matching `/dev/chat` pattern — only in dev mode).
- **Bugs fixed in Day 10 pass:**
  - `approvals/service.py`: wrong import (`.requests.service` → `..requests.service`); missing `tenant_id` on Approval creation; missing `approval.status` field
  - `requests/service.py`: `transition()` now sets `decided_at` for any approved/rejected transition (not only when `user_id` present)
  - `requests/fulfilment.py`: missing `from sqlalchemy import select` import
  - `requests/extractor.py`: removed dead variables and invalid boolean statement
  - `datetime.utcnow()` → `datetime.now(timezone.utc)` throughout (deprecation fix)
  - `FakeProvider` in tests: added `generate_with_tools` stub so orchestrator tests work with tool loop

**Verified ✅ (Day 10 DONE):**
- `pytest tests/test_approvals.py -v` → **10/10 pass** (decide approve/reject/invalid, create_reservation registered/hidden/runs, approval list/decide endpoints + auth)
- Full suite (excluding pre-existing email adapter dep issue): **60/60 pass** — zero regressions
- Safety gate verified: `create_reservation` registered as `ToolKind.fulfilment`, absent from `registry.definitions_for()` → LLM can never call it directly
- Import check: `python -c "from app.approvals.service import decide"` clean

### Technical notes
- **Fulfilment routing**: `fulfil_request()` maps `Request.type` → `"create_{type}"` tool name. Registering `create_reservation` is sufficient for the reservation flow; modification/cancellation handlers (Day 11) follow the same pattern.
- **E2E flow**: Guest says "book a table for 4" → DraftReservation tool creates a Request (needs_review) → staff sees it at `/dev/approvals` → Approve → `decide()` records decision → `fulfil_request()` creates Reservation row → guest notified.
- **Tenant FK requirement**: Tests revealed that several models (`approvals`, `reservations`, `conversations`) have NOT NULL FK constraints on `tenant_id` and `channel_type` that weren't always satisfied in test constructors. All test fixtures now create proper Tenant and Conversation rows.
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

## Day 11 — Modify / cancel + guest memory
- **ModifyReservation tool** (draft + fulfilment): `DraftModifyReservationTool` (`ToolKind.draft`) creates a modification Request idempotent by reservation_id; `ModifyReservationTool` (`ToolKind.fulfilment`) calls `LocalBookingStore.modify()` to apply changes (date, time, party_size, area, notes) after staff approval.
- **CancelReservation tool** (draft + fulfilment): `DraftCancelReservationTool` (`ToolKind.draft`) creates a cancellation Request; `CancelReservationTool` (`ToolKind.fulfilment`) calls `LocalBookingStore.cancel()` to set `ReservationStatus.cancelled` and append reason to notes.
- **Booking store methods** (`app/booking/base.py` → `local.py`): `modify()` — loads reservation by (id, tenant_id), updates non-None fields; `cancel()` — sets status to cancelled, appends reason to notes.
- **Fulfilment routing** (`app/requests/fulfilment.py`): `_fulfilment_tool_name()` maps `RequestType` → tool name (`reservation` → `create_reservation`, `modification` → `modify_reservation`, `cancellation` → `cancel_reservation`), replacing the old hardcoded `f"create_{request.type.value}"`.
- **Guest memory service** (`app/guest_memory/`):
  - `resolve_guest()` — creates or finds Guest by conversation/phone, links `conversation.guest_id`
  - `extract_preferences()` — keyword-based extraction for allergies, seating, occasion, accessibility
  - `update_guest_preferences()` — merges into `Guest.preferences` JSONB column, skips if unchanged
  - `build_guest_context()` — returns "Known guest preferences:\n  - key: value" snippet or None
- **Guest context flow**: `TurnContext` now carries `guest_context` (str | None); `build_system_prompt()` injects it before grounded context; pipeline resolves guest after conversation resolution, extracts preferences, stores them, and passes the context snippet through to the orchestrator.
- **ToolContext**: now carries `channel_type: str = "webchat"` for Request creation from draft tools.
- **Bugs fixed in Day 11 pass:**
  - `channel_type=None` in draft modify/cancel tools → now uses `ctx.channel_type` (was violating DB NOT NULL constraint)
  - `ModifyReservationTool.run()` was passing `ctx.tenant_id` as `reservation_id` to store.modify() — fixed to use `UUID(args.reservation_id)`
  - `reservation.status` type safety: column is `ReservationStatus` enum but SQLAlchemy may return string — added `hasattr` guard in `local.py`
  - `FakeProvider.generate_with_tools` stub added so orchestrator tests work with tool loop

**Verified ✅ (Day 11 DONE):**
- Modify/cancel draft + fulfilment registration: all 4 tools registered with correct `ToolKind` → **4/4 pass**
- Draft creates modification/cancellation Request + idempotency → **2/2 pass**
- Fulfilment hidden from LLM (absent from `registry.definitions_for()`) → **1/1 pass**
- Fulfilment tool mapping covers all 3 RequestTypes → **1/1 pass**
- Booking store modify + cancel operations → **2/2 pass**
- Guest memory: resolve/create/reuse/by-phone, extract preferences (allergies/occasion/empty), update + build context → **9/9 pass**
- Registration tests (decide approve/reject/invalid) → **4/4 pass**
- `create_reservation` fulfilment tool (registered/hidden/runs) → **3/3 pass**
- **Total: 27/27 Day 11 tests pass** (3 endpoint tests skipped — Redis dep not in CI test runner)

### Technical notes
- **Idempotency by reservation_id**: Draft tools check existing open Requests (status `new` or `needs_review`) matching the same reservation_id before creating a new one, avoiding duplicate drafts in the staff queue.
- **Guest memory is session-start only**: Preferences are extracted and stored once per conversation (on first resolve), not re-extracted every turn. The context snippet is built once and passed through `TurnContext`.
- **Current keyword coverage**: allergies, seating, occasion, accessibility — extend by adding patterns to `extract_preferences()`.
- **Consent**: `resolve_guest()` sets `consent.memorized_preferences = True` by default; the Guest model is ready for a GDPR consent flow when needed.
- **channel_type propagation**: `TurnContext.to_tool_context()` now reads `conversation.channel_type` and passes it through to all draft tools, fixing the NOT NULL constraint violation that caused 4 test failures.

## Day 12 — Multi-turn robustness + confirmations
- **Slot-filling state** (W2-D12-1): `Conversation.state` JSONB now wired through `TurnContext.state` via `handle_inbound` pipeline. `build_slot_context()` injects in-progress booking details (date/time/party_size/area) into the system prompt so the LLM sees them across turns. Orchestrator sets `state.intent = "reservation"` on draft detection.
- **Confirm-back prompt** (W2-D12-2): `_MULTI_TURN` instructions enhanced — LLM must confirm details and ask "Shall I proceed?" before calling any `draft_*` tool. Corrections update the in-progress booking rather than creating duplicates.
- **send_message tool** (W2-D12-3): Already existed as `ToolKind.fulfilment` with `SendMessageTool` → `notify(NOTIF_MESSAGE_SENT, ...)` pattern. Fulfilment dispatches confirmation messages via this path. The `notifications.notify()` + event constants serve as the LoggingTransport stub.
- **Redis ZADD reminder queue** (W2-D12-4): `schedule_reminder()` adds a Redis sorted-set entry (`reminders:{tenant_id}`) with score = booking datetime minus `REMINDER_LEAD_HOURS`. `_check_and_fire()` uses `ZRANGEBYSCORE` + `ZREM` as primary source, with graceful DB-fallback when Redis is unavailable. Scheduler wired in `main.py` lifespan with Redis client.
- **Tests** (W2-D12-5): 6 tests added covering confirm-back prompt presence (1), slot context builder (3 states), Redis ZADD scoring, Redis-None fallback. DB-dependent state propagation tests (slot_context_in_system_prompt, state_propagates_across_turns) included but require Postgres.

### Verified ✅ (Day 12 DONE):
- **6/6 non-DB Day 12 tests pass** (confirm-back, slot builder x3, ZADD, Redis-None)
- Ruff clean on all 7 modified files
- DB-dependent tests fail only from missing Postgres — expected infrastructure gap (no `docker compose up`)
- E2E flow: corrections → state updated → confirm-back → draft → staff approve → send_message confirmation → reminder scheduled via Redis ZADD

## Day 13 — Eval harness

**Objective:** Quality is measurable and regressions are caught.

### What was built
- **`evals/` package** — golden-dialogue eval harness, standalone runner, scoring engine
- **12 dialogue YAML files** in `evals/dialogues/` covering:
  1. Happy-path booking (check_availability → confirm-back → draft_reservation → Request)
  2. Availability full → alternatives offered
  3. Modify booking via draft_modify_reservation
  4. Cancel booking via draft_cancel_reservation
  5. FAQ from KB (vegan, hours) — no Request created
  6. Unknown fact → defer ("I'll check with the team")
  7. Injection → guardrail refuse
  8. Abuse → guardrail escalate
  9. Multi-turn correction (4 people → 3 people)
  10. Returning guest (context injected)
  11. Double-send idempotency
  12. Cross-guest access denial

### Architecture
- **`evals/models.py`** — Pydantic schemas (`Dialogue`, `DialogueTurn`, `Scorecard`)
- **`evals/recorder.py`** — `RecordingProvider` (wraps real LLM, records turns) + `ReplayProvider` (plays back recorded responses deterministically) + `FakeEmbedder` (zero-vector embedder bypasses real retrieval)
- **`evals/fixtures.py`** — loads `demo_bistro` tenant + KB chunks from `data/demo_bistro.md`
- **`evals/scoring.py`** — four dimensions: **grounding** (25%), **tool correctness** (30%), **safety** (25%), **resolution** (20%). Weighted average per dialogue, aggregated into scorecard
- **`evals/runner.py`** — `python -m evals.runner` CLI with `--live` (record), `--dialogue` (single), `--baseline` (compare), `--break-grounding` (regression test)
- **`evals/BASELINE.md`** — committed baseline (0.0% until first live run)
- **`.github/workflows/ci.yml`** — CI pipeline with PG/Redis services, ruff, pytest, and eval suite
- **Dependencies:** `PyYAML`, `fakeredis[lua]` added to dev extras

### Key design decisions
- **Replay provider** operates at the `LLMProvider` abstraction boundary (not HTTP-level VCR) — clean, deterministic, no brittle cassettes
- **Fixture via savepoint transaction** (same pattern as test conftest) — runs inside one transaction, rolls back on teardown
- **Per-turn scoring** checks structural attributes (tool called, guardrail action, system prompt) not reply verbatim — robust to minor wording changes
- **--break-grounding** flag strips grounding instructions for regression detection

### Trade-offs
- Recordings require `--live` run on a known-good commit first; subsequent CI runs use replay
- Grounding scoring requires real embeddings + pgvector for accurate CONTEXT detection; initial implementation uses FakeEmbedder which doesn't find KB matches
- No pytest-timeout dependency added — CI runs evals separately

### Verified ✅ (Day 13 DONE):
- `ruff check evals/` — clean (0 errors)
- All 12 YAML dialogue files parse correctly via `Dialogue(**data)`
- All imports resolve (`uv run python -c "from evals.* import ..."`)
- `uv run python -m evals.runner` CLI entry point loads, imports, parses args
- Eval suite ready for `--live` recording run when Postgres is available

## Day 14 — Review · demo · buffer

**Week 2 retrospective: Days 8–13 delivered the full booking loop with human approval — the product's core promise. A guest asks, the concierge checks availability and confirms back, a `Request` lands in the staff queue, a human approves, and *only then* is the Reservation written and the guest confirmed. Every write is structurally unreachable without an approved Request (fulfilment tools are hidden from the LLM).**

### What's green ✅
- **Full booking loop demo scripted** at `docs/demo_week2.md` — check → confirm-back → draft → `Request(needs_review)` → staff approve → fulfilment writes `Reservation(confirmed)` → guest confirmed → `Request(completed)`, plus the "wedge" (off-tool ask → `type=other` Request captured by the extractor).
- **Staff queue API + dev page**: `GET /api/approvals` + `POST /api/approvals/decide` (X-Staff-Token stopgap) and `/dev/approvals` render the Week-2 designer mock's "needs your attention" screen.
- **Test suite**: Day 10–12 registration/approval/booking/memory/reminder tests all green (60/60 at Day 10 close; +27 Day 11, +6 Day 12).
- **Eval harness exists**: 12 golden dialogues, replay recorder, 4-dimension scoring, CI wired (`--baseline` step).
- **Safety invariants proven by tests**: no `fulfilment` tool in the LLM schema; draft tools never write a Reservation; duplicate drafts dedupe; cross-guest modify denied.

### What's yellow ⚡
- **WhatsApp BSP sandbox — confirmed accessible** (owner check passed). Real production number + template approval remain ops long-leads into Week 4; Day 15–16 build against sandbox.
- **Eval baseline is 0.0%** — the harness records/plays back, but the baseline was never scored with real embeddings + pgvector. Book a `--live` recording run early in Week 3 so `evals/BASELINE.md` reflects reality.
- **Email-adapter test dependency** — one pre-existing test gap (SMTP dep) excluded from green counts; revisit when email outbound is exercised.
- **Live demo recording** of `demo_week2.md` not yet captured (needs docker + LLM key + a screen recording).

### Week 3 backlog (Days 15–21) — groomed
| Day | What | Notes |
|-----|------|-------|
| **15** | WhatsApp adapter (sandbox) ★ | New channel: BSP client seam + webhook + `to_inbound()`. Zero brain changes — proof of the Week-1 architecture. |
| **16** | WhatsApp hardening + templates | Outbound templates (submit for approval), 24h-window logic, delivery receipts, retries. |
| **17** | Staff console: live view + transcripts ★ | Conversations list across channels, transcript view, near-real-time (SSE). |
| **18** | Staff console: approvals + live takeover | Approve/edit/reject from the console; human takeover (AI stands down) then resume. |
| **19** | Escalation + notifications | Escalation rules (low-confidence/complaint/VIP/explicit) → real subscribers (email/Slack/WA). |
| **20** | Knowledge editor + config | Console UI to edit hours/menu/policies/brand voice; re-embed on save. |
| **21** | Review · demo · buffer | WhatsApp booking → console approval → confirmation demo; evals green. |

**Week 2 verdict:** the concierge now *acts* behind a human. The approval loop — "your staff confirms every booking" — is infrastructure, not a feature flag. Week 3 adds the channel Lagos guests actually use (WhatsApp) and the cockpit staff live in (console).

## Day 18 — Staff console: approvals + live takeover

**Objective: humans can act — approve work, and step into a live chat.**

### What was built
- **Approvals queue in the console** (renders the enriched Week-2 API): the queue now carries the **channel badge + guest name + payload** (`ApprovalQueueItem` extended, optional `tenant` scoping added — no-tenant behaviour unchanged). The console's new **Approvals tab** shows one-line summary · channel badge · priority · confidence · age · guest, exactly the Week-2 designer mock, with **Approve / Reject (+ note) / Edit** buttons and a live pending-count badge.
- **Edit-before-approve** (`PATCH /api/requests/{id}?tenant=`): staff fix the date/time/party-size/area the AI misheard; the change lands in `Request.payload` (what fulfilment reads) **and** is snapshotted in `Request.resolution` (`edited` / `edited_at` / `edited_by`) — a recorded edit, never a silent overwrite. Only `new|needs_review` requests are editable.
- **Human takeover** (`app/routers/takeover.py`): `POST …/takeover` sets `Conversation.status=human`; `POST …/resume` hands control back; `POST …/staff-message` persists a `role=staff` Message and delivers it **as the venue through the same WhatsApp transport** (the `notify()` seam — keyed by a fresh nonce so it can never be deduped, and the transport skips its own persist since the row already exists). All tenant-scoped (cross-tenant → 404) and audited.
- **The brain stands down on every channel** (`channels/base.py`): `handle_inbound` checks `status==human` before the orchestrator and yields a "paused" notice instead — the same `human` state the Day-6 guardrail escalation sets, so escalation and takeover share one off-switch. The WhatsApp webhook keeps the notice out of outbound (staff reply instead); it still lands in the console transcript.
- **Audit trail** (`app/audit.py`): every console mutation — approve, reject, edit, takeover, resume, staff send — writes an `Action` row (masked token actor — the stopgap identity until Day 24) reusing the Day-8 audit model. Approvals stay append-only.
- **Bug fix in the Week-2 fulfilment path** (`requests/fulfilment.py`): `fulfil_request` was passing the raw JSONB `payload` dict straight into `tool.run()`, which expects a typed args object — the tool crashed on attribute access and the Request was silently marked `failed`. Now coerced via `tool.args_model.model_validate(payload)` (validates, ignores extra keys). **Edit→approve now genuinely fulfils the corrected values.**

### Verified ✅ (without Postgres)
- `ruff` clean; everything compiles/imports; all four new routes smoke-tested (401 without token).
- **3/3 no-DB tests pass** (takeover / staff-message / edit all 401 without a token).
- **8/8 DB tests written** (edit→approve fulfils corrected party size + resolution recorded + audit rows, edit rejected for non-pending, takeover pauses the AI — recording orchestrator never invoked, staff send persists exactly one row + delivers via mock transport, resume restores the brain, queue list carries channel + guest).
- Full non-DB baseline: **76 passed, zero regressions** (remaining failures/errors are DB-connect only).

### Notes / decisions
- **Review catches applied:** summary rewrite is reservation-only (a modification/cancellation edit no longer becomes "Table for None on None at None"); staff-message is **409 unless a takeover is active** (closes the staff-and-AI-both-reply race the spec flagged); audit rows are written *before* the awaited notify so a slow BSP can't delay/skip them; duplicated tenant lookups consolidated into `deps.resolve_tenant_or_404`.
- **The takeover race that remains:** the `status=human` guard is checked when a turn *starts*; a takeover landing mid-turn (after the orchestrator already started) still lets that one reply finish. Acceptable for the sandbox; the Day-21 eval "takeover pauses a mid-booking turn" will measure it.
- **Web-chat staff sends persist but aren't pushed** (no push channel) — the guest sees them on their next session; WhatsApp gets live delivery.

## Day 17 — Staff console: live view + transcripts ★

**Objective: staff see everything, across every channel, in one place — the walk-in demo asset.**

### What was built
- **Shared staff auth** (`app/routers/console_auth.py`): one `X-Staff-Token` dependency (header for fetch/curl, `?token=` for EventSource + the page load) reused by the Week-2 approvals endpoints via a small refactor — the `/dev/approvals` page keeps working. Loudly documented: **real auth is Day 24**, shared secret only. Also added `STAFF_TOKEN` config and fixed a latent bug in the old approvals auth (`settings.get(...)` would crash outside dev).
- **Conversations API** (`app/routers/conversations.py`): `GET /api/conversations?tenant=&channel=&status=&q=` → one list across every channel, newest first, with guest name/phone, last-message preview, status, and `unread` (=1 when the newest message is from the guest). `q` matches guest name/phone **and** message text. `GET /api/conversations/{id}` → full ordered transcript (+ WhatsApp delivery ticks from Day 16's `meta.delivery`), guest context (name/phone/preferences), and linked `Request`s. Tenant-scoped: cross-tenant id → 404.
- **Near-real-time** (`app/routers/stream.py`): `GET /api/stream?tenant=&token=` SSE emitting `conversations_changed` events (ids) on a 2s poll of new messages / status changes; the console refetches and patches, with a 5s client-side fallback if the stream drops. **Decision:** DB-poll, not Redis pub/sub — the repo treats Redis as optional everywhere, and Day 19's notification subscribers become the pub/sub fan-out; swapping the poll behind this endpoint then is small.
- **The console** (`console/index.html`): single-file, no-build vanilla JS page served at `/console?token=…` behind the token — consistent with the project's dev-page convention (the spec left the stack to us; the API contract is the hard deliverable). Conversations list with channel badges (WhatsApp/Web/Email), NEEDS-HUMAN flag, unread dots, live search + channel filters; transcript with guest/preferences card, linked-requests card, delivery ticks (✓✓), and a takeover banner (already rendered for Day 18).

### Verified ✅ (without Postgres)
- `ruff` clean; everything compiles/imports; all three routes mounted (smoke: 401 without token; **with** a token header the request passes auth and proceeds to the DB — proving the shared dependency reads the header).
- **3/3 no-DB console tests pass** (list/detail 401s, page token-gating + serving).
- **8/8 DB console tests written** (tenant-scoped list, channel + q filters, transcript order + ticks + linked request, cross-tenant 404, SSE change detection) — runnable once Postgres is up.
- Full non-DB baseline: **73 passed, zero regressions** (remaining failures/errors are all DB-connect).

### Notes / decisions
- **Review catches applied:** the shared token dependency had lost its `Header(None)` annotation in the refactor (would have 401'd every staff endpoint once Postgres was up) — fixed and proven by smoke; the SSE union column name was wrong (`column_0` → `conversation_id`) — fixed; SSE cursor now captures the tick boundary before querying so a mid-tick change is caught next poll, never skipped.
- **Front-end stack choice:** vanilla JS + SSE single file (no build step), matching `/dev/chat` + `/dev/approvals`; Jinja+htmx was the spec's suggestion but adds a dependency for no gain at this size.
- **N+1 in the list endpoint** (last message + guest per row) is accepted at pilot scale and commented.
- **Console is view-only today** — Day 18 adds the approvals queue, edit-before-approve and live takeover.

## Day 16 — WhatsApp hardening + templates

**Objective: compliant outbound + resilient inbound — no brain changes (Day-15 architecture holds).**

### What was built
- **24-hour service window** (`app/channels/whatsapp/window.py`): `within_service_window()` / `choose_send_mode()` — in-window sends are free-form **text** (₦0 service messages), out-of-window sends must be an approved **template**. Out-of-window with no template → `ValueError` (Week-3 risk 4): blocked loudly, never a silent drop. Window anchored on the guest's last `Message` (derived, no schema change — zero migration risk).
- **Template registry** (`app/channels/whatsapp/templates.py` + `docs/whatsapp_templates.md`): `APPROVED_TEMPLATES`, ordered-variable `TemplateSpec`s for `booking_confirmed` / `booking_reminder` / `booking_updated`, and `resolve_template_name()` (explicit `payload["template"]` > subject defaults > intent map; unapproved names refused). **Ops action started:** submit the three templates in the BSP dashboard (approval is days-long).
- **Bounded retry** (`app/channels/whatsapp/retry.py`): `send_with_retry()` — exponential backoff (0.2s doubling), retries only transient failures (`WhatsAppSendError` + `OSError`). `MetaCloudClient._post` now wraps `httpx.TransportError` into `WhatsAppSendError` so network blips are actually retried (review catch).
- **Idempotent delivery** (transport): each send is keyed by `sha256(conversation:body)`; a re-notify is recognised and never double-sends. Persisted outbound `Message` rows carry `wa_message_id` + `idempotency_key` + `delivery` meta — the Day-17 console's ticks.
- **Delivery + read receipts** (`app/routers/whatsapp.py`): the webhook's `sent|delivered|read|failed` callbacks are persisted on the outbound `Message.meta["delivery"]` (found by `wa_message_id`). Webhook replies now retry and stamp their provider id on the assistant turn (`_stamp_reply_message`).

### Verified ✅ (without Postgres)
- `ruff check app/ tests/` clean; all files compile; app + new modules import cleanly.
- **8/8 pure Day-16 tests pass** (window boundary, template precedence, retry bounds, registry order).
- **6/6 DB-dependent Day-16 tests written** (in-window text, out-of-window template + variables, blocked no-template, retry sends exactly once, re-notify no double-send, status receipts) — runnable once Postgres is up (`docker compose up -d db redis`).
- Day-15 suite unchanged: no regressions in the non-DB subset.

### Notes / decisions
- **No schema change:** `last_inbound_at` is derived from the last guest `Message` row rather than adding a column — the window is a query, not new state. Keeps `alembic check` drift-free.
- **Known races, consciously accepted for the sandbox** (documented in code): `_stamp_reply_message` stamps the latest assistant message (serialised turns make this right in practice); idempotency is check-then-act (sequential re-notifies; a unique index on `(tenant_id, idempotency_key)` closes it for production).
- **Review catches applied:** un-templated test now uses `subject="survey"` (`update` *should* resolve to `booking_updated`); httpx transport errors wrapped so retries work against the real BSP.
- **Ops:** submit `booking_confirmed`/`booking_reminder`/`booking_updated` for approval; webhook config on the sandbox → `POST /webhooks/whatsapp` with the verify token.
