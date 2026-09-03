# Review Backlog — Balance Concierge

Two gstack reviews run against the `concierge/` product on branch `staging`
(reviewed at `07ff4dc` / `56bbf29`):

- **Design review** (`plan-design-review`) — 8 tasks (D1–D8). Overall 4/10.
- **Engineering review** (`plan-eng-review`) — 8 tasks (E1–E8). 11 issues, **4 critical gaps**.

Both ran grounded in actually-read source (no fabrication). Decisions below are
the ones the product owner already made interactively — captured here so the work
survives across sessions.

## Decisions locked (interactive)

| # | Decision | Source |
|---|---|---|
| 1 | Post-draft UX = **set an expectation + non-silent reject** (tell the guest why + offer nearest alternative) | Design review |
| 2 | Staff approval card = **full guest thread + edit-before-approve** (correct party_size/time/area inline) | Design review |
| 3 | Per-tenant voice = **structured schema** (tone register + do/don't examples + length-by-channel), wired through `build_system_prompt` with `channel` passed in | Design review |
| 4 | Eval baseline = **run a first `--live` recording now** (not defer) | Eng review |
| 5 | Per-turn retrieval = **keep always-on** for now (correctness > cost at pilot scale) — E7 effectively dropped | Eng review |
| 6 | Path forward = **write this backlog doc + implement the P1s** | Eng review |

## Still unresolved (need a call before implementation)

| Decision | Tradeoff |
|---|---|
| **Multi-language behavior** (carried from design Pass 7) | detect-and-adapt at runtime vs. declared-locale-only. Risks: wrong locale detection vs. no localization at all. |

## Live-eval constraint (honest)

The eval harness exists (`evals/`, 12 dialogues) but the baseline is **0.0%**
and has never been live-run; scoring currently uses a `FakeEmbedder` that finds
no KB matches. Decision 4 says run it now, but this machine has **no `uv`, no
Postgres/Redis running here, and no live LLM/embeddings key** — so a real
`--live` recording cannot be produced from this environment. To run it:

```bash
cd concierge
docker compose up -d db redis
uv run alembic upgrade head
uv run python scripts/seed.py
uv run python scripts/ingest_kb.py
uv run python -m evals.runner --live        # records; commit evals/recordings + update BASELINE.md
uv run python -m evals.runner               # subsequent CI runs replay + score
```

Until a real baseline exists, **the conversation-quality regression gate that
should protect the per-tenant voice work (D2) is inert.** This is the
highest-leverage test investment and it is blocked on the above infra + a
known-good commit.

---

## P1 — blocks ship (critical / correctness / security)

> LAND NOW. These are either silent-failure paths or proven provenance bugs.

- **E1** — orchestrator — **Make the request extractor durable.**
  `engine.py:180-243` runs `draft_reservation`-aware extraction as
  `asyncio.create_task` with `guest_id=None`, no retry, errors swallowed. On a
  transient LLM failure or worker recycle, the "wedge" request (the most
  valuable message per `demo_week2.md §5`) is *silently lost* — no test, no error
  handling, no guest/staff signal. **Critical gap.**
  *Design choice needed:* durability mechanism (retry-with-backoff + a
  `failed_extraction` dead-letter surfaced in the staff queue, vs in-process
  queue vs out-of-process worker). Recommend explicit dead-letter.
- **E2** — reminders — **Atomic reminder claim so multi-worker doesn't double-fire.**
  `main.py:27` + `reminders/__init__.py:168`: the scheduler is a per-process
  `asyncio.create_task`; Redis `ZRANGEBYSCORE` then `ZREM` (`reminders:107`)
  is **not atomic**, and the DB-fallback dedup `_reminded_set` is process-local.
  Under `--workers N` this double-sends reminders. **Critical gap.**
  *Design choice needed:* Lua `ZRANGEBYSCORE`+`ZREM` script vs a Redis lock vs
  externalize the scheduler entirely. Recommend Lua atomic pop.
- **E3** — fulfilment/tools — **Fix `channel_type` provenance for non-webchat bookings.**
  - `draft_reservation.py:83` sets `channel_type=None` (sister tools at
    `draft_modify:79`/`draft_cancel:65` correctly use `ctx.channel_type`).
  - `fulfilment.py:79-83` builds `ToolContext` with no `channel_type` → defaults
    to `"webchat"` (base.py:22) for **every** fulfilled booking.
  Result: a WhatsApp-originated booking is recorded as `None` at draft, then
  `"webchat"` at fulfilment — never `whatsapp`. Breaks channel attribution +
  reminder-channel selection. **Critical gap. ✅ landing in this pass.**
- **E4** — security — **Fail-closed the WhatsApp webhook when validation has no token.**
  `whatsapp.py:87` only validates `if WHATSAPP_VALIDATE_SIGNATURE and
  TWILIO_AUTH_TOKEN`. `TWILIO_AUTH_TOKEN=""` is the default, so a non-dev deploy
  with WhatsApp routed but no token configured **silently accepts forged inbound
  messages** straight into `draft_reservation`. The existing config fail-closed
  guard doesn't cover this. **Critical gap. ✅ landing in this pass.**
- **D1** — prompt/voice — **Kill the hardcoded current date; make it timezone-aware.**
  `prompt.py:17` hardcodes `"The current real date is 2026-07-28 (Tuesday)"` into
  source — relative-date resolution silently mis-resolves the moment it isn't
  regenerated. `get_hours.py:36` computes "today" in UTC, ignoring
  `tenant.timezone`, so a venue asked "are you open today?" near the boundary
  gets the wrong day's hours. **✅ landing in this pass.**
- **D2** — prompt/voice — **Per-tenant structured voice schema.** (Decision 3.)
  `_BASE` (`prompt.py:7-11`) is identical for every venue; `brand_voice` is one
  free-text `Text` column default `""` (`tenant.py:17`). Add structured fields
  (tone register, do/don't examples, length-by-channel) + pass `channel` into
  `build_system_prompt`. Large, needs the design to pin the schema shape.
- **D3** — orchestrator/voice — **Brand-voice + channel-adapt the "sent to team" message.**
  `engine.py:163-168` hardcodes the post-draft guest message (not brand-voiced,
  not localized, not channel-adapted). Folds in Decision 1: set a time
  expectation; on reject (currently silent, `engine.py:108-130`) tell the guest
  why + offer the nearest alternative via `check_availability`.

## P2 — should land same branch

- **E5** — evals — **First `--live` recording → real baseline** (Decision 4;
  blocked on infra, see constraint above).
- **E6** — llm — **Dedupe the failover cascade + add backoff/jitter.**
  `failover.py:51-81` vs `:83-115` duplicate ~30 lines; no backoff/jitter on
  partial outage (each turn pays the full 30s cascade).
- **D4** — staff surface — **Approvals v1: full thread + edit-before-approve + non-silent reject** (Decision 1 + 2).
- **D5** — states — **Conversation lifecycle map + post-draft waiting state.**
- **D6** — guest memory — **Guest-visible "what I remember" surface + correction + consent.**
- **D7** — a11y — **`aria-live` transcript, visible labels, ≥4.5:1 contrast, 44px targets** on the dev pages (establish tokens so the real staff console inherits them).

## P3 — follow-up (no urgency)

- **E7** — orchestrator — ~~gate/parallelize per-turn retrieval~~ — **dropped per Decision 5** (keep always-on).
- **E8** — tools — **Make `idempotency_key` a queryable Request column**; filter by `conversation_id`. `draft_reservation.py:60-67` loads up to 20 all-tenant open drafts and loops in Python; draft #21 of the same key silently duplicates.
- **D8** — tooling — **Deterministic confirm-back gate before `draft_*`** (or accept prompt-only + document the staff-approval mitigation).

## What already exists (reuse, don't rebuild)

Canonical message contract + streaming chunk protocol · safety tool taxonomy
(`registry` hides `fulfilment` from the LLM) · grounding-with-floor + defer UX ·
per-conversation turn lock · provider-agnostic LLM seam + Azure failover ·
fail-closed config guard for DB/Redis · real-Postgres savepoint test fixture.

## NOT in scope

- **WhatsApp external wiring / Meta verification** — Weeks 3 / Day 15; adapter +
  24h-window logic already built.
- **Real staff auth / RBAC** — Day 24 (`approvals.py:52` placeholder).
- **Marketing/landing visual design** — none exist; this is a conversational
  product. Defer to a future `/design-consultation` if one is ever needed.

## P1 changes landed in this pass

- [x] **D1** — `prompt.py` date now computed from `tenant.timezone`; relative
      examples (`tomorrow`, `this Friday`) computed dynamically. `get_hours.py`
      "today" respects `tenant.timezone`.
- [x] **E3** — `draft_reservation.py` uses `ctx.channel_type`; `fulfilment.py`
      propagates `request.channel_type` into the fulfilment `ToolContext`.
- [x] **E4** — `config.py` fail-closed guard now also rejects a non-dev boot when
      `WHATSAPP_VALIDATE_SIGNATURE` is enabled but `TWILIO_AUTH_TOKEN` is blank.
- [ ] **E1, E2, D2, D3** — design-choice P1s above; not landed (need the
      durability/mechanism/schema calls). E5 (live eval) blocked on local infra.
