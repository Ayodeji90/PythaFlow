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
| Channels: web chat **and email** | `app/channels/webchat.py`, `app/channels/email.py` |
| **Empty tables waiting for this week** | `Reservation`, `Action`, `Approval`, `Guest` (Day 2) |

**The Week-2 thesis:** Week 1 built a concierge that *talks*. Week 2 makes it
**act** — and makes every action a structured, auditable, human-approved
work item. That approval loop is the product's core promise ("your staff confirms
every booking"), so it is built as *infrastructure*, not a feature flag.

## The Request model — the spine of Week 2

The concierge is a **team of staff** for the venue: it handles communication on
every channel, then turns each conversation into **structured work** a human can
accept or decline. A `Request` is that work item — the thing a manager actually
reads in a queue.

```
LAYER 1 · COMMUNICATION            (built)
  email · web chat · WhatsApp · IG/FB · SMS · voice
  every channel → InboundMessage → one brain answers (grounded, guarded)
                     │
LAYER 2 · REQUEST STRUCTURING      (Week 2 — the new spine)
  ├─ draft_* tools    LLM drafts a typed Request mid-conversation (high confidence)
  └─ extractor        post-turn fallback catches what no tool covered
                     │
                     ▼
              Request(needs_review)   type · payload · summary · confidence
                     │
LAYER 3 · HUMAN IN THE LOOP        (Week 2)
  staff queue → accept / edit / decline        ← Approval records the decision
                     │
LAYER 4 · FULFILMENT + REPLY BACK  (Week 2)
  approved → fulfilment handler runs the WRITE (create_reservation, …)
           → artifact (Reservation/Order)
           → outbox: confirm the guest, notify the team
                     │
              Request(completed)
```

**The rule that makes this safe:** during conversation the LLM may only call
**read-only** tools (`get_hours`, `check_availability`). **Every write lives
behind fulfilment**, reachable only from an approved Request. A booking that
skipped a human is not "unlikely" — it is *unreachable by construction*.

**Five objects, five jobs** (keep these boundaries clean and the system stays simple):

| Object | Answers |
|---|---|
| `Message` | what was **said** (raw) |
| **`Request`** | what the customer **wants** (typed, queued, lifecycle) |
| `Action` | what the AI **did** (tool-call audit, immutable) |
| `Approval` | the human **decision event** on a Request |
| `Reservation` / `Order` | the **artifact** produced on fulfilment |

**Standing constraints:** every tool call and query is tenant-scoped; no write
reaches a booking store without an approved `Request`; all new work keeps `ruff`
clean and `alembic check` drift-free.

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
      kind: ToolKind                   # read_only | draft | fulfilment
      async def run(self, args: BaseModel, *, ctx: ToolContext, db: AsyncSession) -> dict: ...
  ```
  **`ToolKind` is the safety boundary, not a label:**
  - `read_only` — callable by the LLM mid-conversation (`get_hours`, `check_availability`)
  - `draft` — callable by the LLM; creates a `Request`, never a booking (`draft_reservation`)
  - `fulfilment` — **not exposed to the LLM at all**; only the fulfilment worker
    may run it, and only for an approved Request (`create_reservation`)

  `registry.schemas_for(tenant)` must expose **only** `read_only` + `draft` tools
  to the model. Add a test asserting no `fulfilment` tool ever appears in a
  generated schema — that assertion is the guarantee behind "no unapproved writes".
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

### W2-D8-5 · The `Request` model + migration  ★ (Day 9 depends on this)
- **Files:** `app/models/request.py`, `app/models/__init__.py`, `app/models/enums.py`,
  new Alembic revision
- **Detail:** the work item at the centre of Layers 2–4.
  ```python
  class Request(UUIDMixin, TenantMixin, TimestampMixin, Base):
      __tablename__ = "requests"
      conversation_id: UUID   # FK conversations, SET NULL
      guest_id:        UUID?  # FK guests, SET NULL
      channel_type:    ChannelType          # denormalised: where it arrived
      type:            RequestType          # see enum below
      status:          RequestStatus        # see enum below
      priority:        RequestPriority      # normal | high (complaints, big parties)
      summary:         str                  # ONE human line staff actually read
      payload:         JSONB                # structured extraction {date,time,party_size,…}
      confidence:      float                # 0–1; low ⇒ forced human review
      assigned_to:     UUID?                # FK users, SET NULL
      resolution:      JSONB                # what was done / why declined
      decided_by:      UUID?                # FK users
      decided_at:      datetime?
  ```
  New enums (VARCHAR + CHECK, per the Day-2 convention):
  ```
  RequestType     reservation | modification | cancellation | order
                  | enquiry | complaint | callback | other
  RequestStatus   new | needs_review | approved | rejected
                  | in_progress | completed | failed | cancelled
  RequestPriority normal | high
  ```
  Indexes: `(tenant_id, status)` — the queue query — and `(conversation_id)`.
  Add `request_id` (FK, SET NULL) to `Approval` so a decision hangs off the Request.
- **Scope discipline:** ship `reservation`, `enquiry`, `other` end-to-end first.
  The other types exist in the enum (cheap, no migration later) but nothing routes
  to them until a pilot venue asks.
- **Done:** `alembic upgrade head` from scratch builds `requests`; `alembic check`
  clean; tenant-isolation test for `requests` mirrors the Day-2 test.

### W2-D8-6 · First tool + tests
- **Files:** `app/tools/get_hours.py`, `tests/test_tools.py`
- **Detail:** `get_hours` reads `Tenant.hours` — trivial, `kind=read_only`.
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

### W2-D9-3 · `check_availability` (read-only) + `draft_reservation` (draft)
- **Files:** `app/tools/check_availability.py`, `app/tools/draft_reservation.py`
- **Detail:**
  - `check_availability` — `kind=read_only`. The LLM calls it freely mid-chat so it
    can say "8:00 is full, 8:30 works?" without touching any write path.
  - `draft_reservation` — `kind=draft`. Creates a **`Request`**
    (`type=reservation`, `status=needs_review`, `confidence=0.95`, structured
    `payload`, one-line `summary`). It creates **no `Reservation` row** — the
    booking itself only exists after approval (W2-D10-4).
- **Idempotency:** key = `sha256(tenant_id|conversation_id|date|time|party_size)`
  stored on the Request payload; re-drafting the same booking **updates the existing
  open Request** instead of stacking duplicates in the staff queue. The Day-2 unique
  `(tenant_id, idempotency_key)` on `Reservation` then guards the fulfilment write.
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
  - [ ] A `Request(type=reservation, status=needs_review)` is created with a
        readable `summary` and structured `payload` — and **no `Reservation` row yet**
  - [ ] **Same booking drafted twice → one open Request** (no duplicate queue noise)
  - [ ] Full slot → `available=false` with alternatives offered
  - [ ] No `fulfilment`-kind tool appears in the schema handed to the LLM

> **Maps to Day 9 checklist:** draft booking · structured pending work item + Sheet
> (on fulfilment) · no double-booking.

---

# Day 10 — Request queue + approval + fulfilment

**Objective:** every conversation becomes structured work a human accepts or
declines — and only then does anything get written or sent.

*This is the day the "team of staff" model becomes real: Layers 2→4 in one loop.*

### W2-D10-1 · Request service (create · dedupe · transition)
- **Files:** `app/requests/service.py`
- **Detail:**
  ```python
  async def open_request(db, *, ctx, type, payload, summary, confidence,
                         priority=normal) -> Request        # dedupes on open key
  async def transition(db, request_id, *, to: RequestStatus,
                       user_id=None, resolution=None) -> Request
  ```
  Legal transitions only (`new|needs_review → approved|rejected`,
  `approved → in_progress → completed|failed`); an illegal transition raises rather
  than silently corrupting the queue. Low `confidence` (< `REQUEST_REVIEW_CONFIDENCE`)
  or `priority=high` can never auto-advance, whatever the tenant config says.

### W2-D10-2 · The extractor (fallback classifier)
- **Files:** `app/requests/extractor.py`
- **Detail:** runs **after** the assistant turn is streamed (never blocking the
  guest's reply — the free-tier latency lesson from Week 1). If the turn already
  produced a Request via a `draft_*` tool, it does nothing. Otherwise it makes one
  cheap **`fast`-tier** call classifying the exchange:
  ```json
  {"type":"complaint","summary":"Cold starter on Friday, wants follow-up",
   "payload":{"visit_date":"2026-07-17"},"confidence":0.72,"priority":"high"}
  ```
  Returning `type: none` is a first-class answer — a pure FAQ ("do you have
  parking?") that the KB already answered creates **no** Request. Anything it
  can't classify becomes `type=other, confidence<0.5` → straight to human review.
- **Why a fallback exists at all:** the `draft_*` tools only cover request types
  we've built. The extractor is what stops *"can I book the terrace for 30 people
  in December?"* — the most valuable message of the week — from being answered
  politely and then vanishing.

### W2-D10-3 · Approval = the decision event
- **Files:** `app/approvals/service.py`
- **Detail:**
  ```python
  async def decide(db, request_id, *, decision, user_id, note=None) -> Approval
  ```
  Writes an `Approval` row (`request_id`, `status`, `decided_by`, `decided_at`) and
  transitions the Request. Approvals are **append-only** — a reversal is a new row,
  never an edit, so the audit trail can't be rewritten.
  `Tenant.config["auto_approve"]` (default **false**) may auto-approve *specific
  low-risk types only* (e.g. `enquiry`), never `reservation`/`order`, and never
  below the confidence floor.

### W2-D10-4 · Fulfilment worker (the only path that writes)
- **Files:** `app/requests/fulfilment.py`, `app/tools/create_reservation.py`
- **Detail:** on approval → `in_progress` → dispatch by `Request.type` to a
  `fulfilment`-kind handler:
  | Request type | Handler | Artifact |
  |---|---|---|
  | `reservation` | `create_reservation` → `BookingStore.create()` + Sheet mirror | `Reservation(confirmed)` |
  | `modification` / `cancellation` | `modify` / `cancel` (Day 11) | updated `Reservation` |
  | `enquiry` / `complaint` | no write — staff reply, logged | — |
  Then `completed` (or `failed` + reason, staying visible in the queue — a silent
  failure is worse than a loud one). Every handler logs an `Action`.

### W2-D10-5 · Staff API (the queue the console will render)
- **Files:** `app/routers/requests.py`
- **Endpoints:**
  - `GET  /api/requests?tenant=<slug>&status=needs_review` → the work queue
  - `GET  /api/requests/{id}` → detail + originating conversation transcript
  - `PATCH /api/requests/{id}` → staff **edit** before approving (fix the party size
    the AI misheard) — the edit is recorded in `resolution`
  - `POST /api/requests/{id}/approve` `{user_id, note?}`
  - `POST /api/requests/{id}/reject` `{user_id, reason}`
- **Detail:** queue rows return `summary`, `type`, `priority`, `channel_type`, age
  and guest name — everything a manager needs to decide in ~3 seconds. Auth is the
  temporary `X-Staff-Token` shared secret; **real auth is Week 3 / Day 24 — document
  the stopgap loudly in the router docstring.**

### W2-D10-6 · Guest + team notification
- **Files:** `app/requests/notify.py`
- **Detail:** on `completed`, write an assistant message into the originating
  conversation ("Confirmed — table for 4 at 8:30pm") and queue a team notification.
  Actual delivery goes through Day 12's outbox, so the same code path later serves
  WhatsApp/email without change.

### W2-D10-7 · Tests
- **Files:** `tests/test_requests.py`, `tests/test_approvals.py`
- **Done:**
  - [ ] A chat booking creates `Request(needs_review)` — and **no `Reservation`**
  - [ ] Guest is **not** told "confirmed" before approval
  - [ ] Approve → fulfilment runs → `Reservation(confirmed)` + guest message + `completed`
  - [ ] `Approval.decided_by` / `decided_at` recorded; reversal appends a second row
  - [ ] Reject → `rejected` + polite guest message, no artifact written
  - [ ] Staff `PATCH` edit before approve is honoured and recorded
  - [ ] Extractor: FAQ turn → **no** Request; unclassifiable turn → `other`, low
        confidence, `needs_review`
  - [ ] **Nothing can write without an approved Request** (attempt fulfilment on a
        `needs_review` Request → raises)

> **Maps to Day 10 checklist:** pending work item · confirm only after approval ·
> audit trail — now with classification and fulfilment closing the loop.

---

# Day 11 — Modify / cancel + guest memory

**Objective:** returning guests are recognized; bookings are editable.

### W2-D11-1 · `modify_reservation` / `cancel_reservation` tools
- **Files:** `app/tools/modify_reservation.py`, `app/tools/cancel_reservation.py`
- **Detail:** the LLM-facing halves are `kind=draft` → they open a
  `Request(type=modification|cancellation)`; the writes are `kind=fulfilment`
  handlers that run only after approval (same split as Day 9/10). Lookup is
  **scoped to this guest / conversation** — a guest must never modify someone
  else's booking (test it). Modify re-checks availability for the new slot before
  drafting the Request.

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
      expect: { tool_called: draft_reservation, request_type: reservation,
                request_status: needs_review, reservation_created: false }
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
  availability, offers an alternative, confirms back → guest says yes →
  **`Request(needs_review)` appears in the queue** (`GET /api/requests`) → staff
  approves via `POST /api/requests/{id}/approve` → fulfilment writes the booking →
  guest sees "Confirmed" → `Reservation(confirmed)` in psql + Sheet + `Request(completed)`.
- **Also demo the wedge:** an off-tool message ("can I book the terrace for 30 in
  December?") producing a `type=other` Request in the same queue — that's the
  moment a venue owner understands what they're buying.

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
TOOLS_MAX_STEPS=4                 # hard cap on the agent loop
AUTO_APPROVE=false                # per-tenant override in Tenant.config; never
                                  # applies to reservation/order types
REQUEST_EXTRACTOR_ENABLED=true    # post-turn fallback classifier
REQUEST_EXTRACTOR_TIER=fast       # cheap model — it's a classification, not prose
REQUEST_REVIEW_CONFIDENCE=0.75    # below this ⇒ always human review
SHEET_ID=                         # Google Sheet mirror (optional; blank disables)
SHEET_CREDENTIALS_JSON=           # service-account JSON path
REMINDER_LEAD_HOURS=24
STAFF_TOKEN_HEADER=X-Staff-Token  # stopgap auth until Week 3/Day 24
```

## What Week 2 deliberately excludes
Real channels (WhatsApp = Day 15) · staff console **UI** (Days 17–20 — Week 2 ships
the API the console renders) · real POS/PMS integration (Day 26 — the adapter seam
is built, the connector isn't) · real staff auth (Day 24) · voice (Phase 1).

## For the designer — the staff queue screen

`GET /api/requests?status=needs_review` returns everything this screen needs. The
mock doubles as the **walk-in demo asset** (it's the screen an owner will actually
live in), and it becomes the Day 17–20 console spec — so the design work is
never throwaway.

```
┌──────────────────────────────────────────────────────────────┐
│  Needs your attention  (3)                    Demo Bistro ▾  │
├──────────────────────────────────────────────────────────────┤
│ ⬤ HIGH  🍽 RESERVATION            via WhatsApp · 4 min ago    │
│   Table for 4 — Fri 8:30pm, window seat                      │
│   Chidera A.  ·  "anniversary dinner"                        │
│                        [ View chat ]  [ Decline ]  [ Accept ]│
├──────────────────────────────────────────────────────────────┤
│ ⬤ HIGH  ⚠ OTHER                   via Email · 1 hr ago       │
│   Private terrace booking, 30 guests, December               │
│                        [ View chat ]  [ Decline ]  [ Accept ]│
├──────────────────────────────────────────────────────────────┤
│         💬 ENQUIRY                via Instagram · 2 hr ago   │
│   Asked about vegan options — answered from menu ✓           │
│                                            [ View chat ]     │
└──────────────────────────────────────────────────────────────┘
```

Design notes that matter: the **one-line summary** is the whole product (a manager
decides in ~3 seconds); the **channel badge** shows the concierge covers every
surface; **Accept/Decline** must feel weightless (this is the human-in-the-loop
promise made tangible); and an *answered* enquiry with no action needed proves the
AI is filtering noise rather than adding it.

## The Week-2 risks to watch

**1. Misclassification is the failure mode that matters.** A wrong `type` is
recoverable (staff re-type it); a request that *silently disappears* is not. Hence
the rules: unclassifiable → `other` at low confidence, never dropped; low
confidence → forced human review; `type: none` is only legitimate when the KB
already answered a pure FAQ. Add an eval dialogue for each.

**2. Tool-calling reliability on small/free models.** Day 1 showed llama-3.1-8b
following instructions loosely; tool-calling is stricter still. If `quality`-tier
tool calls prove flaky on the free tier, the mitigation is provider-swap (the seam
already supports it — Groq/OpenAI have solid tool support), *not* rewriting the
loop. Budget a half-day for this on Day 8.
