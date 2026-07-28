# Concierge — Week 3 Build Spec (developer-ready tickets)

*Expands Days 15–21 of [Concierge_30_Day_Sprint.md](./Concierge_30_Day_Sprint.md)
into concrete tickets: exact files, signatures, endpoints, and acceptance
criteria. Same format as the [Week 1](./Concierge_Week1_Build_Spec.md) and
[Week 2](./Concierge_Week2_Build_Spec.md) specs — hand a day to a developer and
they can start.*

---

## Where Week 2 left off (what you're building on)

| Already built | Where |
|---|---|
| Channel-agnostic pipeline (`handle_inbound`) + adapter pattern | `app/channels/base.py`, `webchat.py`, `email.py` |
| Tool-calling loop (read-only + draft tools) | `app/orchestrator/tools_loop.py`, `app/tools/` |
| Request spine: create · dedupe · transition | `app/requests/service.py` |
| Fallback classifier | `app/requests/extractor.py` |
| Approval = decision event · fulfilment (the only write path) | `app/approvals/service.py`, `app/requests/fulfilment.py` |
| Request/approval **API** (the queue the console renders) | `app/routers/approvals.py` |
| **Notification seam** — `notify(event, …)` + subscriber pattern (logs today, real channels tomorrow) | `app/notifications/__init__.py` |
| Reminder scheduler (Redis due-queue + DB fallback, lifespan) | `app/reminders/__init__.py` |
| Guest identity + consent + returning-guest context | `app/guest_memory/__init__.py` |
| Guardrails → `escalate` sets `Conversation.status=human` | `app/orchestrator/guardrails.py`, `app/orchestrator/engine.py` |
| KB ingest · chunk · embed · retrieve | `app/knowledge/ingest.py`, `retrieve.py`, `app/routers/knowledge.py` |
| Eval harness (12 golden dialogues) | `evals/` |

**The Week-3 thesis:** Week 1 made it *talk*, Week 2 made it *act* behind a human.
Week 3 does two things: **give the concierge a new surface** (WhatsApp — the channel
Lagos guests actually use) and **give the humans a cockpit** (the staff console where
the approval promise becomes a daily tool). Nothing about the *brain* changes for
either — WhatsApp is a new **adapter**, the console is a new **client of the API**.
That the brain doesn't move is the proof the Week-1/2 architecture was right.

```
LAYER 1 · COMMUNICATION          + WhatsApp adapter (Day 15–16)  ← new surface
  every channel → InboundMessage → one brain (grounded, guarded, tool-using)
                     │
LAYER 2–4 · REQUEST → HUMAN → FULFILMENT      (built in Week 2)
                     │
      ┌──────────────┴───────────────────────────────────┐
      ▼                                                   ▼
STAFF CONSOLE (Day 17–20)  ← new cockpit          OUTBOUND (Day 15–16, 19)
  live conversations · transcripts                  notify() → WhatsApp / email
  approvals queue · edit · takeover                  / Slack subscribers
  escalation inbox · KB + config editor
```

**Standing constraints (unchanged, still enforced):** every query/tool call is
tenant-scoped; **no write reaches a booking store without an approved `Request`**;
the LLM is still handed only `read_only` + `draft` tool schemas; all new work keeps
`ruff` clean and `alembic check` drift-free. **Real staff auth is Day 24** — the
console ships this week on the `X-Staff-Token` stopgap, documented loudly.

**Long-lead gate:** Day 15 depends on **WhatsApp BSP sandbox access** (the Day-14
check). If it's still blocked, run the documented fallback — **web-chat-only pilot** —
and slide Days 15–16 without blocking Days 17–20 (the console has independent value).

---

# Day 15 — WhatsApp adapter (sandbox) ★

**Objective:** the same brain now answers on WhatsApp — with **zero brain changes**.

### W3-D15-1 · BSP client + config
- **Files:** `app/channels/whatsapp/client.py`, `app/config.py` (update)
- **Detail:** a thin BSP wrapper (360dialog **or** Twilio — pick per the account
  provisioned Day 1) behind a small interface, mirroring the LLM-provider seam so the
  BSP is swappable:
  ```python
  class WhatsAppClient(Protocol):
      async def send_text(self, *, to: str, body: str) -> str          # returns provider msg id
      async def send_template(self, *, to: str, name: str, vars: dict) -> str
  ```
  Config keys (below in "New config keys"): `WHATSAPP_BSP`, `WHATSAPP_TOKEN`,
  `WHATSAPP_PHONE_ID`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`.
- **Done:** a one-off script sends a text to a sandbox number and returns a provider id.

### W3-D15-2 · Inbound webhook → `InboundMessage`
- **Files:** `app/channels/whatsapp/adapter.py`, `app/routers/whatsapp.py`
- **Endpoints:**
  - `GET  /webhooks/whatsapp` — verification challenge (echo `hub.challenge` when
    `hub.verify_token` matches `WHATSAPP_VERIFY_TOKEN`).
  - `POST /webhooks/whatsapp` — inbound events. **Verify the `X-Hub-Signature-256`
    HMAC** against `WHATSAPP_APP_SECRET` before trusting the body.
- **Detail:** `to_inbound(payload) -> InboundMessage` — the *only* new mapping code.
  It sets `channel=ChannelType.whatsapp`, `conversation_ref=<wa_id>`, and
  `sender.phone=<wa_id>`, then calls the **existing** `handle_inbound()` untouched.
  The phone on `sender` is what finally makes `guest_memory.resolve_guest()` fire
  (web chat had no phone) — returning WhatsApp guests are now recognised.
- **Done:** a WhatsApp message to the sandbox number round-trips through the real
  orchestrator and a reply is sent back.

### W3-D15-3 · Outbound transport = a `notifications` subscriber
- **Files:** `app/channels/whatsapp/transport.py`, register in `app/notifications/__init__.py`
- **Detail:** the reply path is **not** new plumbing — register a WhatsApp subscriber
  on the existing `notify()` seam so `NOTIF_MESSAGE_SENT` (confirmations, reminders,
  fulfilment replies) delivers over WhatsApp when the conversation's channel is
  `whatsapp`. This is the "transport swap, not rewrite" the Week-2 notification seam
  was built for. Streaming tokens collapse to a single WhatsApp message (no token
  streaming on WA).
- **Done:** an assistant turn on a WhatsApp conversation is delivered to the handset.

### W3-D15-4 · Zero-brain-change proof + tests
- **Files:** `tests/test_whatsapp_adapter.py`
- **Done:**
  - [ ] Inbound WA payload → correct `InboundMessage` (fake BSP, no network)
  - [ ] Bad/missing `X-Hub-Signature-256` → **401**, body never processed
  - [ ] A WA conversation produces a concierge reply via the same engine path
  - [ ] **Diff proof:** `git diff` for this day touches only `channels/whatsapp/*`,
        the router, and config — **no change to `orchestrator/` or `tools/`**

> **Maps to Day 15 checklist:** WA message gets a reply · zero brain changes · inbound + outbound end-to-end.

---

# Day 16 — WhatsApp hardening + templates

**Objective:** compliant outbound + resilient inbound.

### W3-D16-1 · Message templates (confirmations / reminders)
- **Files:** `app/channels/whatsapp/templates.py`, `docs/whatsapp_templates.md`
- **Detail:** define + **submit for approval** the outbound templates the product
  needs: `booking_confirmed`, `booking_reminder`, `booking_updated`. Store the
  approved template name + variable order in a small registry; `send_template()`
  fills variables. Submission is an **ops action started today** — approval takes
  days (mirror the Day-1 long-lead discipline).
- **Done:** at least `booking_confirmed` submitted; registry maps event → template.

### W3-D16-2 · 24-hour service window logic
- **Files:** `app/channels/whatsapp/window.py`
- **Detail:** Meta rule — inside the 24h window since the guest's last message you may
  send **free-form** text (a *service* message, free); outside it you **must** send an
  approved **template**. Track `last_inbound_at` per conversation; the WhatsApp
  transport chooses free-text vs template automatically. (This is also the cost lever
  from the business model — service messages are ₦0.)
- **Done:** in-window reply sends as text; a simulated out-of-window send uses a template.

### W3-D16-3 · Delivery + read receipts
- **Files:** `app/routers/whatsapp.py` (status branch), `app/models/conversation.py` (Message.meta)
- **Detail:** the same webhook receives `sent|delivered|read|failed` status callbacks;
  record them on the outbound `Message.meta` so the console (Day 17) can show ticks.
- **Done:** an outbound message's status transitions are persisted.

### W3-D16-4 · Retries + send idempotency
- **Files:** `app/notifications/__init__.py` (delivery retry), `app/channels/whatsapp/transport.py`
- **Detail:** transient send failures retry with backoff (bounded); dedupe on the
  provider message id so a retry never double-sends. A permanent failure logs + marks
  the Message `failed` (visible, never silent — the Week-2 rule).
- **Done:** a forced transient failure is retried and eventually delivered exactly once.

### W3-D16-5 · Tests
- **Files:** `tests/test_whatsapp_hardening.py`
- **Done:**
  - [ ] In-window → text; out-of-window → template chosen automatically
  - [ ] Status callback updates `Message.meta`
  - [ ] Send failure retried and logged; no double-send under retry

> **Maps to Day 16 checklist:** template submitted · in-window round-trips reliably · failures retried + logged.

---

# Day 17 — Staff console: live view + transcripts ★

**Objective:** staff can see everything, across every channel, in one place.

### W3-D17-1 · Console app scaffold + stopgap auth
- **Files:** `console/` (new lightweight front end), `app/routers/console_auth.py`
- **Stack:** recommended **server-rendered Jinja + htmx + SSE** — no separate build,
  SSR, trivial live updates, fastest for a small team; a minimal Vite+React SPA against
  the same JSON API is an acceptable alternative. **The hard deliverable is the API
  contract; the front-end stack is the team's call.** The console is also the **walk-in
  demo asset** (the screen an owner lives in), so it doubles as a sales surface.
- **Auth:** `X-Staff-Token` shared secret (per-tenant), checked by a dependency.
  **Document loudly that real auth is Day 24.**
- **Done:** `/console` loads behind the token; unauthenticated → 401.

### W3-D17-2 · Conversations list
- **Files:** `app/routers/conversations.py`, console list screen
- **Endpoint:** `GET /api/conversations?tenant=<slug>&channel=&status=&q=` →
  rows: `{id, channel_type, guest_name, last_message_preview, status, unread, updated_at}`,
  newest first, tenant-scoped.
- **Done:** web **and** WhatsApp conversations appear in one list with channel badges.

### W3-D17-3 · Transcript view
- **Files:** `app/routers/conversations.py` (detail), console transcript screen
- **Endpoint:** `GET /api/conversations/{id}` → full ordered `Message[]`
  (`role`, `content`, `created_at`, delivery `meta`) + guest context + any linked
  `Request`s. Tenant-scoped; cross-tenant id → 404.
- **Done:** opening a conversation shows the complete transcript with WA delivery ticks.

### W3-D17-4 · Near-real-time updates
- **Files:** `app/routers/stream.py` (SSE), console subscriber
- **Detail:** `GET /api/stream?tenant=<slug>` Server-Sent Events; publish a lightweight
  event on new `Message` / new `Request` / status change (fan-out via Redis pub/sub so
  it works across workers). Console appends without a full reload; **poll fallback**
  every 5s if SSE drops.
- **Done:** a new inbound message appears in the open list/transcript within ~2s, no reload.

### W3-D17-5 · Tests
- **Files:** `tests/test_console_views.py`
- **Done:**
  - [ ] List returns only the caller's tenant; channel filter works
  - [ ] Transcript returns full ordered history; cross-tenant id → 404
  - [ ] SSE emits an event on a new message (fake publisher)

> **Maps to Day 17 checklist:** live web + WA conversations in one list · transcript opens · near-real-time.

---

# Day 18 — Staff console: approvals + live takeover

**Objective:** humans can act — approve work, and step into a live chat.

### W3-D18-1 · Approvals queue UI (renders the Week-2 API)
- **Files:** console queue screen (consumes `app/routers/approvals.py`)
- **Detail:** render `GET /api/requests?status=needs_review` exactly as the **Week-2
  designer mock** specified (one-line summary · channel badge · priority · age · guest).
  Wire the buttons to the endpoints Week 2 shipped: approve / reject / edit. (If a
  queue-**list** endpoint isn't already in `approvals.py`, add it here — the decision
  endpoints already exist.)
- **Done:** a manager approves / rejects a booking from the console in ~3 seconds.

### W3-D18-2 · Edit-before-approve
- **Files:** `app/routers/approvals.py` (PATCH), console edit affordance
- **Detail:** `PATCH /api/requests/{id}` lets staff fix the party size/time the AI
  misheard **before** approving; the change is recorded in `Request.resolution` (never
  a silent overwrite). Approval then fulfils the corrected payload.
- **Done:** an edited-then-approved booking fulfils the corrected values; edit is audited.

### W3-D18-3 · Human takeover (AI stands down → staff sends → resume)
- **Files:** `app/routers/takeover.py`, `app/channels/base.py` (guard), `app/orchestrator/engine.py` (guard)
- **Detail:** `POST /api/conversations/{id}/takeover` sets `Conversation.status=human`;
  **the pipeline must not let the AI answer while status is `human`** — add the guard in
  `handle_inbound()` (before the orchestrator) so the brain stands down on *every*
  channel. Staff messages send **as the venue** through the same outbound transport.
  `POST /api/conversations/{id}/resume` returns control (`status=active`). This reuses
  the exact `status=human` state guardrail escalation already sets — takeover is the
  manual trigger for it.
- **Done:** staff take over a live WhatsApp chat, the AI pauses, staff reply lands on the
  guest's phone, resume hands control back.

### W3-D18-4 · Audit everything
- **Files:** reuse `app/tools/logging.py` / `Action` + `Approval`
- **Detail:** every console mutation (approve, reject, edit, takeover, resume, staff
  send) writes an audit row with `decided_by`/actor + timestamp. Approvals stay
  **append-only** (a reversal is a new row).
- **Done:** the audit trail shows who did what, when, for each action.

### W3-D18-5 · Tests
- **Files:** `tests/test_console_actions.py`
- **Done:**
  - [ ] Approve/reject/edit from the API drive the Week-2 fulfilment path correctly
  - [ ] During takeover the orchestrator is **not** invoked; staff send delivers
  - [ ] Resume restores AI handling
  - [ ] Every action is audited with actor + timestamp

> **Maps to Day 18 checklist:** approve/edit/reject from console · takeover pauses then resumes the AI · every action audited.

---

# Day 19 — Escalation + notifications

**Objective:** the right things reach a human fast, on the channel staff actually watch.

### W3-D19-1 · Escalation rules
- **Files:** `app/orchestrator/escalation.py`, `Tenant.config["escalation"]`
- **Detail:** a small rule set producing an escalation on: **low confidence**
  (`Request.confidence < REQUEST_REVIEW_CONFIDENCE`), **complaint** type, **VIP** guest
  (`Guest.preferences.vip`), or **explicit ask** ("let me speak to someone"). Reuses the
  signals already present — guardrails' `escalate`, the extractor's `type/priority`,
  Request `priority=high`. Escalation flags the conversation and bumps the Request
  priority; it does **not** invent new state.
- **Done:** each trigger type produces an escalation + flags the conversation.

### W3-D19-2 · Real notification subscribers + routing
- **Files:** `app/notifications/email.py`, `app/notifications/slack.py` (+ WA from Day 15), `Tenant.config["notify"]`
- **Detail:** graduate the Week-2 `notify()` seam from log-stub to **real subscribers** —
  email / Slack webhook / WhatsApp-to-staff / dashboard push — chosen per tenant by
  `Tenant.config["notify"]`. Adding a channel is adding a subscriber; **callers don't
  change** (the seam's whole point). Escalations route here.
- **Done:** an escalation delivers a real notification on the tenant's configured channel.

### W3-D19-3 · Handoff surface in the console
- **Files:** console "Needs a human" inbox
- **Detail:** escalated conversations surface in a dedicated inbox at the top of the
  console and link straight into **takeover** (Day 18) — a clean AI→human handoff in one
  click.
- **Done:** an escalated chat appears in the inbox and one click takes the human in.

### W3-D19-4 · Tests
- **Files:** `tests/test_escalation.py`
- **Done:**
  - [ ] Each escalation type (low-confidence, complaint, VIP, explicit ask) fires + flags
  - [ ] A notification is dispatched to the configured subscriber (fake transport)
  - [ ] Handoff → takeover works end-to-end

> **Maps to Day 19 checklist:** each escalation type notifies + flags · AI→human handoff is clean.

---

# Day 20 — Knowledge editor + config

**Objective:** staff can run it without us — edit the venue's facts and voice, live.

### W3-D20-1 · KB editor
- **Files:** `app/routers/knowledge.py` (extend), console KB screen
- **Endpoints:** `GET /api/kb?tenant=<slug>` (list sources), `PUT /api/kb/{source}`
  (replace a source's text), `DELETE /api/kb/{source}`. On write → re-chunk + re-embed
  via the existing `knowledge/ingest.py` (reuse, don't rebuild) and replace that
  source's chunks atomically (tenant-scoped).
- **Done:** editing hours/menu/policy text in the console changes grounded answers within minutes.

### W3-D20-2 · Brand voice + config editor
- **Files:** `app/routers/tenant_config.py`, console settings screen
- **Detail:** edit `Tenant.brand_voice`, `languages`, capacity rules
  (`covers_per_slot`, `slot_minutes`, `service_hours`), `auto_approve` (still never for
  `reservation`/`order`), and `escalation`/`notify` config. Validated writes; a bad
  config is rejected, not half-applied.
- **Done:** a brand-voice change visibly shifts the concierge's tone on the next turn.

### W3-D20-3 · Live re-embed + cache invalidation
- **Files:** `app/knowledge/ingest.py` (invalidate), `app/orchestrator/state.py` (bust cached persona)
- **Detail:** saving KB re-embeds only the changed source; saving config busts any cached
  system prompt so edits take effect on the next turn, not the next restart.
- **Done:** hours/rules edits take effect live (verify by re-asking after a save).

### W3-D20-4 · Tests
- **Files:** `tests/test_kb_editor.py`
- **Done:**
  - [ ] Editing a KB source re-embeds and changes retrieval results
  - [ ] Deleting a source removes its chunks (tenant-scoped; can't touch another tenant)
  - [ ] Invalid config rejected; valid config changes behaviour next turn

> **Maps to Day 20 checklist:** KB edit changes answers in minutes · brand-voice change shifts tone · hours/rules edits live.

---

# Day 21 — Review · demo · buffer

**Objective:** the full channel + console loop is demonstrable; Week 4 is groomed.

### W3-D21-1 · End-to-end demo
- **Files:** `docs/demo_week3.md` (+ recording)
- **Script:** a guest books **via WhatsApp** → concierge checks availability, confirms
  back → `Request(needs_review)` appears in the **console** → staff approve → fulfilment
  writes the booking → **confirmation delivered over WhatsApp** (`booking_confirmed`
  template if out of window) → `Reservation(confirmed)` in psql + Sheet + `Request(completed)`.
  Then trigger an **escalation** (a complaint) → staff get notified → take over the live
  WhatsApp chat → resume.
- **Done:** the above runs clean, recorded.

### W3-D21-2 · Evals + regression
- **Files:** `evals/` (add channel/console coverage where feasible)
- **Done:** eval suite green; add/adjust dialogues for takeover-pauses-AI and
  escalation; `ruff` clean; `alembic check` clean.

### W3-D21-3 · Groom + log
- **Done:**
  - [ ] `SPRINT_LOG.md` Week-3 entry (decisions + surprises)
  - [ ] Week-4 backlog groomed (multilingual, analytics, security/GDPR, reliability,
        pilot onboarding, dry run, soft launch)
  - [ ] WhatsApp production-access status checked (sandbox → production is its own lead time)

> **Maps to Day 21 checklist:** WA booking → console approval → confirmation sent · escalation end-to-end · Week 4 groomed.

---

## New config keys introduced this week

```
# WhatsApp / BSP (Day 15–16)
WHATSAPP_BSP=360dialog            # 360dialog | twilio
WHATSAPP_TOKEN=                   # BSP API token
WHATSAPP_PHONE_ID=                # sender phone-number id
WHATSAPP_VERIFY_TOKEN=            # webhook verification (GET challenge)
WHATSAPP_APP_SECRET=              # HMAC secret for X-Hub-Signature-256
WHATSAPP_TEMPLATE_CONFIRM=booking_confirmed
WHATSAPP_TEMPLATE_REMINDER=booking_reminder

# Console (Day 17–18) — stopgap until Day 24 real auth
STAFF_TOKEN_HEADER=X-Staff-Token
CONSOLE_SSE_ENABLED=true

# Escalation / notifications (Day 19) — real values per tenant in Tenant.config
NOTIFY_SLACK_WEBHOOK=             # optional; blank disables
NOTIFY_EMAIL_FROM=
```

## What Week 3 deliberately excludes
Real staff **auth/SSO + RBAC** → **Day 24** (this week runs on `X-Staff-Token`) ·
multilingual → **Day 22** · analytics dashboard → **Day 23** · real POS/PMS connector
→ **Day 26** (the `BookingStore` seam is ready, the connector isn't) · voice → **Phase 1**.
WhatsApp is built to **sandbox**; production number + business verification remain an
ops long-lead tracked into Week 4.

## For the designer — the console

Four screens, one cockpit. The **approvals queue** is the Week-2 mock (reuse it
verbatim — it's already the walk-in demo asset). The three new screens:

**Conversations (live, all channels)**
```
┌───────────────────────────────────────────────── Demo Bistro ▾ ──┐
│  Conversations           [ All ▾ ] [ WhatsApp ▾ ] [ Needs human ] │
├───────────────────────────────────────────────────────────────────┤
│ 💬 WhatsApp  Chidera A.        "8:30 works, thank you!"    · 12s ✓✓│
│ ✉ Email      Tunde O.         "Do you cater 30 for Dec…"  · 4m    │
│ 💬 Web       (anon)           "vegan mains?"  answered ✓   · 9m    │
│ ⚠ WhatsApp  Ada N.  NEEDS HUMAN  "this is unacceptable"   · 1m 🔴 │
└───────────────────────────────────────────────────────────────────┘
```

**Transcript + takeover**
```
┌── Chidera A. · WhatsApp ─────────────────────  [ Take over ] ─────┐
│  Guest   any tables for 4, Fri 8?                        23:41    │
│  Concierge  8:00 is full — 8:30 works? …                23:41 ✓✓ │
│  Guest   8:30 works, thank you!                          23:42    │
│  ── linked request: RESERVATION · needs review → [queue] ──       │
│  … AI paused while you're in control …                            │
│  [ type as the venue…                                    ] [Send] │
└───────────────────────────────────────────────────────────────────┘
```

**KB + config editor**
```
┌── Knowledge ──────────────────────────────────────────────────────┐
│  Hours        Mon–Thu 12–23 · Fri–Sat 12–24 · Sun 12–22   [edit]  │
│  Menu         menu.md  (re-embedded 2 min ago)            [edit]  │
│  Policies     deposits, cancellations                     [edit]  │
│  Brand voice  "Warm, concise — like a great maître d'."   [edit]  │
│  Saving re-embeds the changed source and updates answers live.    │
└───────────────────────────────────────────────────────────────────┘
```

Design notes that matter: **takeover must feel instant and obvious** (the human-in-
the-loop promise, made physical); the **channel badge is everywhere** (proof the
concierge covers every surface a guest uses); **"NEEDS HUMAN" is the loudest thing on
the screen**; and an *answered* conversation with no action shows the AI is removing
work, not adding it.

## The Week-3 risks to watch

**1. BSP + template approval latency is the schedule risk, not the code.** Sandbox
access and template approval each take days and are outside your control. Submit
templates Day 16 morning; if sandbox is blocked, take the documented **web-chat-only
pilot** cut and build the console (Days 17–20) in parallel — it has standalone value
and is the actual sales asset.

**2. Takeover race conditions.** Between "staff clicks take over" and "AI mid-reply"
there's a window where both could answer. Put the `status=human` guard in
`handle_inbound()` (before the orchestrator) and check it again immediately before any
outbound send, so a takeover mid-turn cleanly wins. Add an eval for "takeover pauses a
mid-booking turn."

**3. Console auth is a real hole until Day 24.** `X-Staff-Token` is a shared secret with
no per-user identity, so "who approved this" is only as trustworthy as token hygiene.
Keep the token server-side, per-tenant, rotate on demand, and never ship the console to
the open internet before Day 24. Say so in the router docstrings.

**4. The 24-hour window will bite outbound.** A reminder or confirmation sent >24h after
the guest's last message **fails silently as free text** — it must be a template. Route
*all* proactive outbound through the window check (W3-D16-2); make an un-templated
out-of-window send a loud error, never a quiet drop.
