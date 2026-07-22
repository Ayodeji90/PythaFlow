# Concierge — Week 2 Build Spec (developer-ready tickets)

*Expands Days 8–14 of [Concierge_30_Day_Sprint.md](./Concierge_30_Day_Sprint.md)
into concrete tickets: exact files, signatures, and acceptance criteria. Same
format as the [Week 1 spec](./Concierge_Week1_Build_Spec.md) — hand a day to a
developer and they can start.*

---

## Where Week 1 left off (what you're building on)

| Already built | Where |
|---|---|
| Channel-agnostic pipeline (`handle_inbound`) | `app/channels/base.py` |
| Orchestrator seam + `TurnContext` | `app/orchestrator/base.py` |
| LLM seam with `generate()` + `stream()` | `app/llm/service.py`, `providers/openai_compatible.py` |
| RAG grounding + similarity floor | `app/knowledge/retrieve.py` |
| Guardrails (rules + LLM moderator) | `app/orchestrator/guardrails.py` |
| Per-conversation turn lock | `app/services/locks.py` |
| **Empty tables waiting for this week** | `Reservation`, `Action`, `Approval`, `Guest` (Day 2) |

**The Week-2 thesis:** Week 1 built a concierge that *talks*. Week 2 makes it
**act** — and makes every action auditable and human-approved. That approval loop
is the product's core promise ("your staff confirms every booking"), so it is
built as *infrastructure*, not a feature flag.

**Standing constraints:** every tool call is tenant-scoped; nothing writes to a
"real" booking store without an `Approval`; all new work keeps `ruff` clean and
`alembic check` drift-free.

---

# Day 8 — Tool-calling framework

**Objective:** the brain can *act*, and every action is logged.

### W2-D8-1 · Tool contract + registry
- **Files:** `app/tools/base.py`, `app/tools/registry.py`, `app/tools/__init__.py`
- **Detail:**
  ```python
  class ToolContext(BaseModel):        # what every tool needs, injected not guessed
      tenant_id: UUID; conversation_id: UUID; guest_id: UUID | None

  class Tool(Protocol):
      name: str                        # snake_case, matches the LLM function name
      description: str                 # shown to the model
      args_model: type[BaseModel]      # pydantic = the JSON schema AND the validator
      requires_approval: bool          # True for guarded writes (Day 10)
      async def run(self, args: BaseModel, *, ctx: ToolContext, db: AsyncSession) -> dict: ...
  ```
  `registry.py`: `register(tool)`, `get(name)`, `schemas_for(tenant)` →
  OpenAI-style `tools=[{"type":"function", ...}]` generated from `args_model`.
- **Why pydantic-as-schema:** one definition produces both the model-facing JSON
  schema and the runtime validator — they can never drift apart.

### W2-D8-2 · Tool-calling loop in the LLM seam
- **Files:** `app/llm/base.py`, `app/llm/providers/openai_compatible.py`, `app/llm/service.py`
- **Detail:** add `generate_with_tools(messages, *, tier, system, tools) -> LLMToolResult`
  where `LLMToolResult = {text: str | None, tool_calls: list[ToolCall]}`.
  `ToolCall = {id, name, arguments: dict}`.
  - Non-streaming for tool turns (streaming a tool call is meaningless); we stream
    only the **final** natural-language answer.
  - Base class default: providers without tool support raise
    `ToolsUnsupportedError` — the seam stays honest.

### W2-D8-3 · Agent loop in the orchestrator
- **Files:** `app/orchestrator/engine.py` (update), `app/orchestrator/tools_loop.py`
- **Detail:** after guardrails + retrieval, run:
  ```
  for step in range(MAX_TOOL_STEPS):        # settings.TOOLS_MAX_STEPS, default 4
      result = await llm.generate_with_tools(...)
      if not result.tool_calls: break        # model is ready to answer
      for call in result.tool_calls:
          validate args -> run tool -> append tool result to messages
          yield OutboundChunk(type="action", content=call.name, metadata={...})
  stream the final answer as tokens (existing path)
  ```
  A hard step cap prevents infinite tool loops burning tokens.

### W2-D8-4 · Action logging + graceful arg failure
- **Files:** `app/tools/logging.py` (or inside `tools_loop.py`)
- **Detail:** every call writes an `Action` row (`type`, `input`, `output`,
  `status ∈ proposed|executed|failed`). On `ValidationError`, log
  `status=failed`, return the validation message **to the model** as the tool
  result so it can retry with correct args — never crash the turn.

### W2-D8-5 · First tool + tests
- **Files:** `app/tools/get_hours.py`, `tests/test_tools.py`
- **Detail:** `get_hours` reads `Tenant.hours` — trivial, read-only, `requires_approval=False`.
- **Done:**
  - [ ] LLM invokes `get_hours` and an `Action` row is written with `status=executed`
  - [ ] Invalid args (e.g. `party_size="four"`) → `status=failed`, model gets the
        error, turn completes with a sensible reply (no crash)
  - [ ] Tool-loop tests use a **fake LLM** that emits scripted tool calls (no network)

> **Maps to Day 8 checklist:** tool invoked + logged · invalid args rejected gracefully.

---

# Day 9 — Availability + booking backend (manual/Sheet fallback) ★

**Objective:** it can check and draft a reservation.

### W2-D9-1 · Booking-store adapter seam
- **Files:** `app/booking/base.py`, `app/booking/local.py`, `app/booking/factory.py`
- **Detail:** same swappable pattern as the LLM seam — Day 26+ swaps in a real
  PMS/POS without touching tools:
  ```python
  class BookingStore(Protocol):
      async def check_availability(self, *, tenant_id, date, time, party_size) -> AvailabilityResult
      async def create(self, draft: ReservationDraft) -> Reservation
      async def modify(self, reservation_id, changes) -> Reservation
      async def cancel(self, reservation_id, reason) -> Reservation
  ```
  `LocalBookingStore` = Postgres `reservations` table + tenant capacity rules
  from `Tenant.config` (`{"covers_per_slot": 20, "slot_minutes": 30, "service_hours": …}`).

### W2-D9-2 · Availability logic
- **Files:** `app/booking/availability.py`
- **Detail:** given date/time/party, check (a) inside `Tenant.hours`, (b) sum of
  `party_size` for confirmed+approved reservations in that slot < capacity.
  Return `AvailabilityResult{available: bool, alternatives: list[time]}` — the
  alternatives are what make the concierge feel competent ("8:00 is full, 8:30?").

### W2-D9-3 · `check_availability` + `create_reservation` tools
- **Files:** `app/tools/check_availability.py`, `app/tools/create_reservation.py`
- **Detail:** `create_reservation` has `requires_approval=True` and writes
  `status=pending`. **Idempotency:** key = `sha256(tenant_id|conversation_id|date|time|party_size)`
  → the Day-2 unique `(tenant_id, idempotency_key)` makes a retry return the
  *existing* row instead of a duplicate.
- **Note:** natural-language dates ("tomorrow", "Friday 8pm") resolve in the tool
  using `Tenant.timezone`, not in the prompt — models are unreliable at date math.

### W2-D9-4 · Google Sheet mirror (pilot booking "system")
- **Files:** `app/booking/sheet_mirror.py`, config `SHEET_ID`, `SHEET_CREDENTIALS_JSON`
- **Detail:** append/update a row per reservation so a pilot venue watches
  bookings arrive in a familiar spreadsheet. **Best-effort:** failures log a
  warning and never fail the booking (the DB is the source of truth).

### W2-D9-5 · Tests
- **Files:** `tests/test_booking.py`
- **Done:**
  - [ ] Chat can check availability and draft a booking
  - [ ] `Reservation` row created with `status=pending` (+ Sheet mirror attempted)
  - [ ] **Same request twice → one row** (idempotency proven)
  - [ ] Full slot → `available=false` with alternatives offered

> **Maps to Day 9 checklist:** draft booking · pending row + Sheet · no double-booking.

---

# Day 10 — Write-action approval flow

**Objective:** nothing hits the real store without a human.

### W2-D10-1 · Approval service
- **Files:** `app/approvals/service.py`
- **Detail:**
  ```python
  async def request_approval(db, *, action, reservation=None) -> Approval   # status=pending
  async def decide(db, approval_id, *, decision, user_id, note=None) -> Approval
  ```
  On **approve**: reservation → `confirmed`, `Action.status=executed`, booking
  store `create()` committed, guest confirmation queued.
  On **reject**: reservation → `rejected`, guest told politely, conversation flagged.
  Per-tenant config `Tenant.config["auto_approve"]` (default **false**) allows a
  trusting venue to skip the gate later — the default is always human-in-the-loop.

### W2-D10-2 · Staff approvals API
- **Files:** `app/routers/approvals.py`
- **Endpoints:**
  - `GET /api/approvals?tenant=<slug>&status=pending` → queue for the Week-3 console
  - `POST /api/approvals/{id}/approve` `{user_id, note?}`
  - `POST /api/approvals/{id}/reject` `{user_id, reason}`
- **Detail:** auth is a temporary shared-secret header (`X-Staff-Token` from
  `Tenant.config`) — real auth is Week 3/Day 24. **Document the stopgap loudly.**

### W2-D10-3 · Guest-side confirmation on approve
- **Files:** `app/approvals/notify.py`
- **Detail:** on approval, push a message into the guest's conversation
  (persisted as `role=assistant`) so the guest sees "Confirmed — table for 4 at
  8:30pm." Delivery to a live channel is Day 12's `SendMessage`.

### W2-D10-4 · Tests
- **Files:** `tests/test_approvals.py`
- **Done:**
  - [ ] A chat booking creates a **pending** `Approval`
  - [ ] Guest is **not** told "confirmed" before approval
  - [ ] After approve → reservation `confirmed` + guest message written
  - [ ] `Approval.decided_by` / `decided_at` recorded (audit trail)
  - [ ] Reject path → `rejected` + polite guest message

> **Maps to Day 10 checklist:** pending approval · confirm only after approval · audit trail.

---

# Day 11 — Modify / cancel + guest memory

**Objective:** returning guests are recognized; bookings are editable.

### W2-D11-1 · `modify_reservation` / `cancel_reservation` tools
- **Files:** `app/tools/modify_reservation.py`, `app/tools/cancel_reservation.py`
- **Detail:** both `requires_approval=True`. Lookup is **scoped to this guest /
  conversation** — a guest must never modify someone else's booking (test it).
  Modify re-checks availability for the new slot before drafting.

### W2-D11-2 · Guest identity + memory
- **Files:** `app/guests/identity.py`, update `app/channels/base.py`
- **Detail:** `resolve_guest(db, tenant_id, sender) -> Guest | None` matching on
  `phone`, else `handles[channel]`. Web chat stays anonymous (no signal) —
  WhatsApp (Day 15) provides the phone, which is when this becomes valuable.
  On resolve: attach `guest_id` to the conversation, bump `last_seen_at`.
- **Prompt:** `build_system_prompt(..., guest=...)` adds a short "returning guest"
  line (name + last visit + preferences). Keep it ≤2 lines; it's context, not a dossier.

### W2-D11-3 · Consent capture
- **Files:** `app/guests/consent.py`
- **Detail:** `Guest.consent = {"marketing": bool, "recording": bool, "ts": iso}`.
  Never assume opt-in. This is the hook Day-24 GDPR work builds on.

### W2-D11-4 · Tests
- **Files:** `tests/test_guest_memory.py`
- **Done:**
  - [ ] Change and cancel a booking via chat (each through approval)
  - [ ] Returning guest (same phone) greeted with context
  - [ ] **Cross-guest access denied** — cannot modify another guest's reservation
  - [ ] Consent flag stored and defaults to false

> **Maps to Day 11 checklist:** modify/cancel · returning guest recognized · consent stored.

---

# Day 12 — Multi-turn robustness + confirmations

**Objective:** it survives messy real conversations.

### W2-D12-1 · Slot-filling state
- **Files:** `app/orchestrator/booking_state.py`, uses `Conversation.state` (JSONB, Day 2)
- **Detail:** track the in-progress booking (`date`, `time`, `party_size`,
  `area`, `notes`) across turns. A correction ("actually 4 people, 7pm") **updates
  the same draft** rather than starting a new one. Clear on completion/cancel.
- **Why state, not just history:** relying on the model to re-read history for
  slots is where multi-turn bookings break in practice.

### W2-D12-2 · Ambiguity + confirm-back
- **Files:** `app/orchestrator/prompt.py` (update)
- **Detail:** before a write tool runs, the concierge must **restate the booking
  and get a yes** ("Table for 4, Friday 7pm — shall I request that?"). This is
  the cheapest hallucination guard that exists and mirrors how a real host works.

### W2-D12-3 · `send_message` + outbound queue
- **Files:** `app/tools/send_message.py`, `app/services/outbox.py`
- **Detail:** an `outbox` abstraction with a `LoggingTransport` stub for now
  (real SMS/email is Week 3+). Confirmations and reminders both go through it, so
  Day 15's WhatsApp becomes a transport swap, not a rewrite.

### W2-D12-4 · Reminder scheduling
- **Files:** `app/services/scheduler.py`
- **Detail:** Redis sorted-set `due` queue (`ZADD reminders <ts> <payload>`) + an
  async worker polling for due items. Schedule "day-before" reminders on
  confirmation. Deliberately *not* Celery — one dependency-light worker.

### W2-D12-5 · Tests
- **Files:** `tests/test_multiturn.py`
- **Done:**
  - [ ] Messy correction mid-booking handled ("actually 4 people, 7pm" → one draft, updated)
  - [ ] Confirm-back happens before any write tool runs
  - [ ] A confirmation is sent via the outbox stub
  - [ ] A scheduled reminder fires in a test (time injected, not slept)

> **Maps to Day 12 checklist:** correction handled · confirmation sent · reminder fires.

---

# Day 13 — Eval harness

**Objective:** quality is measurable and regressions are caught.

### W2-D13-1 · Golden-dialogue format + runner
- **Files:** `evals/dialogues/*.yaml`, `evals/runner.py`
- **Detail:**
  ```yaml
  name: books_a_table_after_confirmation
  tenant_fixture: demo_bistro
  turns:
    - guest: "table for 2 friday 8pm?"
      expect: { tool_called: check_availability, confirm_back: true }
    - guest: "yes please"
      expect: { tool_called: create_reservation, reservation_status: pending }
  ```
  Runner drives the real orchestrator against a **fixture tenant + KB**, with the
  LLM either live (`--live`) or replayed from recorded responses (default, so CI
  is deterministic and free).

### W2-D13-2 · The scored dimensions
- **Files:** `evals/scoring.py`
- **Detail:** per dialogue — **grounding** (claims traceable to retrieved chunks
  or tool output), **tool correctness** (right tool, valid args), **safety**
  (refusal/escalation when required), **resolution** (goal achieved). Emit a
  JSON scorecard + a human-readable table.

### W2-D13-3 · The starting suite (≥12 dialogues)
Cover: happy-path booking · availability-full-with-alternatives · modify · cancel ·
FAQ from KB (hours/vegan) · **unknown fact → defer** · injection → refuse ·
abuse → escalate · multi-turn correction · returning guest · double-send
idempotency · cross-guest access denial.

### W2-D13-4 · CI + baseline
- **Files:** `.github/workflows/ci.yml` (update), `evals/BASELINE.md`
- **Done:**
  - [ ] `uv run python -m evals.runner` gives clear pass/fail
  - [ ] A **deliberately broken prompt** (grounding instruction removed) is caught
  - [ ] Baseline scores committed to `evals/BASELINE.md`

> **Maps to Day 13 checklist:** suite runs pass/fail · regression caught · baseline recorded.

---

# Day 14 — Review · demo · buffer

**Objective:** the full booking loop is demonstrable, and Week 3's long-lead risk is retired.

### W2-D14-1 · End-to-end demo
- **Files:** `docs/demo_week2.md` (+ recording)
- **Script:** guest asks hours (grounded) → asks for a table → concierge checks
  availability, offers an alternative, confirms back → guest says yes → **pending**
  approval → staff approves via `POST /api/approvals/{id}/approve` → guest sees
  "Confirmed" → reservation `confirmed` in psql + Sheet.

### W2-D14-2 · WhatsApp BSP sandbox — **critical long-lead check**
- **Done:** sandbox access confirmed and a test message sent. If still blocked,
  **escalate now** — Day 15 depends on it. Fallback: web-chat-only pilot (already
  the documented cut in the sprint plan's "if you fall behind").

### W2-D14-3 · Groom + log
- **Done:**
  - [ ] Demo recorded; `pytest` + evals green; `ruff` clean; `alembic check` clean
  - [ ] `SPRINT_LOG.md` Week-2 entry written (decisions + surprises)
  - [ ] Week-3 backlog groomed (WhatsApp adapter, staff console)

> **Maps to Day 14 checklist:** booking-loop demo · evals green + BSP confirmed · backlog groomed.

---

## New config keys introduced this week

```
TOOLS_MAX_STEPS=4            # hard cap on the agent loop
AUTO_APPROVE=false           # per-tenant override in Tenant.config
SHEET_ID=                    # Google Sheet mirror (optional; blank disables)
SHEET_CREDENTIALS_JSON=      # service-account JSON path
REMINDER_LEAD_HOURS=24
STAFF_TOKEN_HEADER=X-Staff-Token   # stopgap auth until Week 3/Day 24
```

## What Week 2 deliberately excludes
Real channels (WhatsApp = Day 15) · staff console UI (Days 17–20) · real POS/PMS
integration (Day 26 — the adapter seam is built, the connector isn't) · real staff
auth (Day 24) · voice (Phase 1).

## The Week-2 risk to watch
**Tool-calling reliability on small/free models.** Day 1 showed llama-3.1-8b
following instructions loosely; tool-calling is stricter still. If `quality`-tier
tool calls prove flaky on the free tier, the mitigation is provider-swap (the seam
already supports it — Groq/OpenAI have solid tool support), *not* rewriting the
loop. Budget a half-day for this on Day 8.
