# PythaFlow Concierge — First 30-Day Sprint (Phase 0: text-first)

*Turns [Concierge_System_Plan.md](./Concierge_System_Plan.md) into a daily build
schedule. Locked scope: **text-first, one venue** — web chat + WhatsApp text,
grounded answers, reservations with staff approval, in a multi-tenant system with
a staff console. Voice is Phase 1 (next sprint).*

---

## North Star (what "done" means on Day 30)

> A guest can message one pilot venue on **web chat or WhatsApp**, get **accurate,
> on-brand answers**, and **make / change a reservation** that a staff member
> **approves in a console** — all multi-tenant, logged, and safe. Live in a
> limited soft-launch, measured against a real baseline.

**If we hit only 80%:** cut WhatsApp (web-chat-only pilot), cut multilingual and
analytics polish. **Never cut:** grounding/guardrails, the approval flow, and the
staff console. Those are the trust.

---

## Assumptions & how to read this

- **Team:** 1–3 focused builders. Solo = doable but tight; parallelize the
  starred (★) days if you have more hands.
- **Cadence:** 5 build days/week; **Day 7/14/21 = review + demo + buffer** (real
  buffer, not filler — that's where slippage is absorbed).
- **Each day has:** an **Objective**, **Tasks**, and a **Done checklist** — every
  checklist item is *verifiable* (you can point at a passing test, a 200 response,
  a row in a table, or a working demo). A day isn't done until every box is ticked.
- **Reuse the repo:** the existing FastAPI backend + LLM provider abstraction
  (`llm_service` + `providers/`) is the starting point — don't rebuild it.

## Long-lead items — start Day 1, in parallel (they gate the finish)

- [ ] **WhatsApp/Meta Business verification + BSP** (360dialog or Twilio) —
  approval takes days. Submit Day 1 or WhatsApp won't be ready by Week 3.
- [ ] **LLM API keys** (Anthropic/OpenAI) and provider budget.
- [ ] **Pilot venue confirmed** + their real hours/menu/policies collected.
- [ ] **Hosting + data region** decided (drives compliance).

## Daily operating rhythm (every build day)

1. **Morning (10 min):** read the day's Objective; confirm yesterday's boxes are
   all ticked (if not, it rolls over — adjust honestly).
2. **Build.**
3. **End of day (15 min):** tick the Done checklist, commit, write one line in a
   `SPRINT_LOG.md` (what shipped / what's blocked), demo to yourself.
4. **Definition of Done (applies to every task):** code committed + a test or a
   reproducible manual check + no regression in the eval suite (once it exists).

---

# WEEK 1 — Foundations & the first real conversation

### Day 1 — Project skeleton + kick off long-lead items ★
**Objective:** the service runs locally and the approval clocks start ticking.
**Tasks:** scaffold service (FastAPI, Postgres, Redis, pgvector) with
`docker compose`; secrets/env; health endpoint; issue tracker seeded with these 30
days; **submit Meta Business verification + pick a WhatsApp BSP**; verify LLM key.
- [ ] `docker compose up` runs; `GET /health` → 200
- [ ] Postgres + Redis + pgvector reachable from the app
- [ ] Meta Business verification **submitted**; BSP account requested
- [ ] LLM key works via a one-off test call
- [ ] 30-day tickets created in the tracker

### Day 2 — Data model & multi-tenancy
**Objective:** every row belongs to a tenant.
**Tasks:** schema — `Tenant, User, Channel, Conversation, Message, Guest,
Reservation, Action/Approval, KnowledgeChunk(+embedding)`; migrations; tenant_id
scoping; seed one tenant + staff user.
- [ ] Migrations apply cleanly from scratch
- [ ] Seed script creates a tenant + staff user
- [ ] A query proves data is isolated by `tenant_id`
- [ ] ERD committed to the repo

### Day 3 — Canonical Message + orchestrator skeleton + web-chat echo
**Objective:** a message round-trips through the system.
**Tasks:** define canonical `Message`/`Event` schema; orchestrator interface
(`receive → process → reply`); web-chat WebSocket endpoint; wire a test page (or
the marketing-site widget) to it; **echo** first.
- [ ] Message sent in web chat comes back (echo)
- [ ] The message is persisted under the right tenant + conversation
- [ ] Canonical Message schema documented in the repo

### Day 4 — LLM in the loop (ungrounded, streaming)
**Objective:** it talks like the venue.
**Tasks:** plug LLM (via existing abstraction) into the orchestrator; per-tenant
brand-voice system prompt; stream tokens to web chat; conversation state (history
from DB, context-window management, Redis hot state).
- [ ] Web chat returns a coherent LLM reply in the tenant's persona
- [ ] Multi-turn works (reply references an earlier message)
- [ ] Responses stream token-by-token

### Day 5 — Knowledge base + RAG (grounded answers)
**Objective:** answers come from the venue's real facts.
**Tasks:** KB ingestion (docs → chunk → embed → pgvector); retrieval injected into
the prompt; load **one venue's real KB** (hours, menu, policies).
- [ ] "What are your hours?" / "Vegan options?" → correct, grounded answer
- [ ] Retrieval returns relevant chunks (spot-checked)
- [ ] Unknown fact → "I don't have that — let me get a human" (no invention)

### Day 6 — Guardrails v1 + grounding discipline
**Objective:** it won't lie or wander.
**Tasks:** answer only from KB/tools else refuse/deflect; scope/abuse/PII handling;
"confirm before any write" scaffolding; low-confidence → escalate flag.
- [ ] Adversarial prompts (invent a price, off-topic) → safe deflection
- [ ] PII redacted in logs
- [ ] A small scripted guardrail test set passes

### Day 7 — Review · demo · buffer
**Objective:** a real, grounded web-chat concierge exists.
- [ ] End-to-end demo recorded (grounded Q&A, one venue)
- [ ] Test suite green; bugs from the week fixed
- [ ] Meta verification status checked; Week 2 backlog groomed

---

# WEEK 2 — Tools, reservations & memory

### Day 8 — Tool-calling framework
**Objective:** the brain can *act*, and every action is logged.
**Tasks:** function-calling loop; tool registry; typed + validated tool interface;
log every call to `Action`; dry-run/confirm pattern.
- [ ] The LLM invokes a first tool (e.g., `GetHours`) and it's logged
- [ ] Invalid tool args are rejected gracefully (no crash)

### Day 9 — Availability + booking backend (manual/Sheet fallback) ★
**Objective:** it can check and draft a reservation.
**Tasks:** `CheckAvailability` + `CreateReservation` backed by Postgres +
**Google Sheet mirror** as the pilot "booking system"; idempotency keys.
- [ ] Chat can check availability and draft a booking
- [ ] Reservation row created (`status=pending`) + mirrored to the Sheet
- [ ] Duplicate request does **not** double-book (idempotency proven)

### Day 10 — Write-action approval flow
**Objective:** nothing hits the real store without a human.
**Tasks:** pending write → **Approvals queue**; finalize only on approval (per
tenant config); confirmation message to guest on approve.
- [ ] A chat booking creates a **pending** Approval
- [ ] Guest is confirmed only *after* staff approval
- [ ] Audit trail records who approved and when

### Day 11 — Modify / cancel + guest memory
**Objective:** returning guests are recognized; bookings are editable.
**Tasks:** `ModifyReservation`, `CancelReservation`; `Guest` profile + history
(match by phone/handle); preference + **consent** capture.
- [ ] Change and cancel a booking via chat (through approval)
- [ ] A returning guest is greeted with context
- [ ] Consent flag stored on the guest

### Day 12 — Multi-turn robustness + confirmations
**Objective:** it survives messy real conversations.
**Tasks:** handle corrections/ambiguity ("actually 4 people, 7pm"); `SendMessage`
/ confirmation (email/SMS stub); reminder scheduling via job queue.
- [ ] A messy correction mid-booking is handled correctly
- [ ] A confirmation is sent (stub is fine)
- [ ] A scheduled reminder fires in a test

### Day 13 — Eval harness
**Objective:** quality is measurable and regressions are caught.
**Tasks:** golden-dialogue test suite (book, FAQ, refuse, modify) run in CI;
metrics (resolution, grounding).
- [ ] Eval suite runs with clear pass/fail
- [ ] A deliberately broken prompt is caught by the suite
- [ ] Baseline scores recorded in the repo

### Day 14 — Review · demo · buffer
- [ ] Demo: full booking loop **with approval** in web chat
- [ ] Eval green; WhatsApp BSP **sandbox access confirmed** (critical long-lead check)
- [ ] Week 3 backlog groomed

---

# WEEK 3 — Channels + human-in-the-loop console

### Day 15 — WhatsApp adapter (sandbox) ★
**Objective:** the same brain now answers on WhatsApp.
**Tasks:** WhatsApp adapter via BSP sandbox; inbound webhook → canonical Message;
outbound reply; number + opt-in.
- [ ] A WhatsApp message to the sandbox number gets a concierge reply
- [ ] **Zero brain changes** — only the adapter differs (proves the architecture)
- [ ] Inbound + outbound text both work end-to-end

### Day 16 — WhatsApp hardening + templates
**Objective:** compliant outbound + resilient inbound.
**Tasks:** submit outbound **templates** (confirmations/reminders) for approval;
delivery/read receipts; 24h-window logic; retries.
- [ ] Outbound template submitted for approval
- [ ] Inbound-within-window round-trips reliably
- [ ] Send failures are retried and logged

### Day 17 — Staff console: live view + transcripts ★
**Objective:** staff can see everything.
**Tasks:** extend the dashboard — list conversations across channels, open a
transcript, near-real-time updates.
- [ ] Staff see live conversations (web + WhatsApp) in one list
- [ ] Full transcript opens per conversation
- [ ] New messages appear near-real-time

### Day 18 — Staff console: approvals + live takeover
**Objective:** humans can act.
**Tasks:** approvals queue UI (approve/edit/reject bookings + outbound); human
**takeover** (AI stands down, staff sends as the venue), then resume.
- [ ] Staff approve/edit/reject a booking from the console
- [ ] Staff take over a live chat; the AI pauses; then resumes
- [ ] Every action is audited

### Day 19 — Escalation + notifications
**Objective:** the right things reach a human fast.
**Tasks:** escalation rules (low-confidence / complaint / VIP / explicit ask) →
notify staff (email/SMS/Slack); routing.
- [ ] Each escalation type triggers a staff notification + flags the conversation
- [ ] Handoff from AI to human works cleanly

### Day 20 — Knowledge editor + config
**Objective:** staff can run it without us.
**Tasks:** console UI to edit hours/menu/policies/brand voice/escalation rules;
re-embed on save.
- [ ] Editing the KB in the console changes answers within minutes
- [ ] A brand-voice change visibly shifts the tone
- [ ] Hours/rules edits take effect live

### Day 21 — Review · demo · buffer
- [ ] Demo: guest books via **WhatsApp** → staff approves in console → confirmation sent
- [ ] An escalation is demonstrated end-to-end
- [ ] Week 4 backlog groomed

---

# WEEK 4 — Harden, pilot-ready, soft launch

### Day 22 — Multilingual
**Objective:** meet guests in their language.
**Tasks:** detect language, reply in it; staff-facing text stays in the business
language.
- [ ] Converse + book in 2–3 languages
- [ ] Transcript shows original (and translation for staff)

### Day 23 — Analytics
**Objective:** prove value with numbers.
**Tasks:** dashboard — conversations, bookings captured, deflection rate, response
time, escalations, estimated revenue recovered.
- [ ] Dashboard shows real metrics from live conversations

### Day 24 — Security & compliance basics
**Objective:** safe to touch real guest data.
**Tasks:** isolation review; encryption in transit/at rest; secrets hygiene;
**data export + delete** endpoints (GDPR); consent logging; rate limits.
- [ ] Delete-guest endpoint fully wipes that guest's data
- [ ] Tenant A cannot access Tenant B's data (tested)
- [ ] No secrets in code; rate limiting active

### Day 25 — Reliability & fallbacks
**Objective:** it degrades gracefully, never crashes.
**Tasks:** queue-based resilience; provider-outage fallbacks ("we'll get back to
you" / human); idempotency review; retries; monitoring + alerts.
- [ ] Simulated LLM/WhatsApp outage → graceful fallback + alert, no crash
- [ ] No double-writes under retry
- [ ] Basic uptime/error alerting works

### Day 26 — Onboard the real pilot venue
**Objective:** the actual venue is fully configured.
**Tasks:** load real KB/hours/menu/brand voice/booking process/escalation
contacts; create staff accounts; train staff on the console.
- [ ] Pilot tenant fully configured with real data
- [ ] Staff can log in and use the console
- [ ] Test bookings succeed end-to-end

### Day 27 — Full internal dry run
**Objective:** find the breakage before guests do.
**Tasks:** 20+ realistic conversations (scripted + freeform) across web + WhatsApp;
edge cases; log a punch-list.
- [ ] 20+ conversations run; all bookings correct; escalations correct
- [ ] Punch-list captured and prioritized

### Day 28 — Clear punch-list + eval regression
**Objective:** green light on quality.
- [ ] Punch-list cleared or consciously triaged
- [ ] Eval suite green; latency acceptable on both channels

### Day 29 — Soft launch (limited / after-hours, humans approving all)
**Objective:** real guests, tight scope, close watch.
**Tasks:** go live for the pilot venue in limited scope (e.g., after-hours web +
WhatsApp), **every write human-approved**; monitor live; incident plan ready.
- [ ] A real guest is handled end-to-end successfully
- [ ] Staff are comfortable; metrics are flowing
- [ ] Incident/rollback plan documented

### Day 30 — Review, measure, plan the next 30
**Objective:** decide and set up Phase 1 (voice).
**Tasks:** measure vs baseline (recovered bookings / questions handled); retro;
go/expand decision; outline the **self-built voice** sprint.
- [ ] Pilot results documented against a real baseline
- [ ] Go / no-go / expand decision made
- [ ] Phase 1 (Twilio + Deepgram + TTS voice) sprint outline drafted

---

## Weekly definition-of-done (the four demos that matter)

| End of | You can demo… |
|---|---|
| **Week 1** | A grounded web-chat concierge answering from one venue's real knowledge |
| **Week 2** | A full booking loop (check → draft → **staff-approve** → confirm) in web chat |
| **Week 3** | The same, on **WhatsApp**, with a live staff console + escalation |
| **Week 4** | A configured pilot venue, **soft-launched** to real guests, measured |

## If you fall behind (cut in this order)
1. Multilingual (Day 22) → later
2. Analytics polish (Day 23) → minimal metrics only
3. WhatsApp (Days 15–16) → **web-chat-only pilot** (still proves everything)
4. **Never cut:** grounding/guardrails, approval flow, staff console, security basics.
