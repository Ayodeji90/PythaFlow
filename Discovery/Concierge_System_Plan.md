# PythaFlow Concierge — System Architecture & Build Plan

*Planning document. No implementation — this defines **what we build and in what
order** so the code phase is unambiguous.*

---

## 1. Goal

One AI concierge that handles **every guest conversation on every channel** for a
hospitality business — inbound & outbound **phone calls**, **SMS**, **WhatsApp**,
**Instagram / Messenger**, **web chat**, and **email** — plus proactive jobs like
**review replies** and **reminders**. It answers questions, takes and changes
**reservations/orders**, upsells, and hands off to staff when it should — in the
guest's language, in the venue's brand voice, with humans in control.

### Design principles
1. **Channel-agnostic brain.** One conversation engine; channels are thin,
   swappable adapters. Adding a channel must never touch the brain.
2. **Buy the plumbing, own the brain.** Commodity telephony/STT/TTS/messaging =
   vendors. Our moat = orchestration, tools, knowledge, guest memory, and the
   human-in-the-loop console.
3. **Provider-agnostic AI.** Reuse the repo's existing LLM abstraction — no model
   or vendor lock-in. Same pattern for telephony, messaging, and booking vendors.
4. **Text first, voice second.** Text is cheaper, safer, and faster to prove.
   Voice reuses the *same* brain with an audio front-end bolted on.
5. **Humans in the loop by default.** Every money/guest-facing write action can
   require staff approval, tightening only as trust is earned.
6. **Multi-tenant from line one.** Every business is a tenant with isolated data,
   config, knowledge, and brand voice.

---

## 2. Capability scope (what "smart" means)

| Area | Capabilities |
|---|---|
| **Answer** | Hours, location/directions, menu, dietary/allergen, rooms & amenities, policies, parking, events — grounded in the venue's own knowledge base. |
| **Transact** | Check availability; create / modify / cancel **reservations** (tables & rooms); take **orders / room service**; capture waitlist & leads. |
| **Voice** | Answer **inbound calls** (after-hours or full-time / overflow); place **outbound calls** (confirmations, reminders, waitlist call-backs). |
| **Proactive** | Booking confirmations & reminders, no-show reduction, post-stay review requests, **draft replies to Google reviews**. |
| **Revenue** | Contextual upsell (pairings, add-ons, experiences, upgrades) in brand voice. |
| **Handoff** | Escalate to a human on complaints, VIPs, low confidence, or explicit request — warm transfer on voice, live takeover on text. |
| **Global** | Detect and converse in the guest's language; keep staff-facing text in the business's language. |

---

## 3. System architecture (the shape)

```
                 GUEST CHANNELS
  Phone · SMS · WhatsApp · IG/Messenger · Web chat · Email
        │        │        │         │          │        │
        ▼        ▼        ▼         ▼          ▼        ▼
┌──────────────────────────────────────────────────────────┐
│  CHANNEL GATEWAY  (thin adapters, one per provider)        │
│  normalises everything to a canonical Message/Event        │
│  { tenant, channel, conversationId, sender, content, … }   │
└──────────────────────────────────────────────────────────┘
        │ (text)              │ (audio stream)
        ▼                     ▼
                       ┌──────────────┐
                       │ VOICE FRONT-  │  STT ⇄ TTS, turn-taking,
                       │ END (audio)   │  barge-in, VAD  ← swappable
                       └──────┬───────┘
        │  ┌──────────────────┘  (audio ⇄ text)
        ▼  ▼
┌──────────────────────────────────────────────────────────┐
│  CONVERSATION ORCHESTRATOR  ("the brain")                  │
│  • session & state          • language detect              │
│  • intent / routing         • LLM orchestration (tools)    │
│  • RAG over tenant KB        • guardrails & confirmations   │
└───────────────┬───────────────────────────┬──────────────┘
                │ calls tools                │ retrieves
                ▼                            ▼
┌───────────────────────────┐   ┌───────────────────────────┐
│  SKILLS / TOOLS            │   │  KNOWLEDGE + MEMORY        │
│  availability, reserve,    │   │  KB (vector), guest        │
│  order, FAQ, lead, review, │   │  profiles, conversation    │
│  notify, transfer-to-human │   │  history, per-tenant config│
└─────────────┬─────────────┘   └───────────────────────────┘
              │ via adapters
              ▼
┌──────────────────────────────────────────────────────────┐
│  INTEGRATIONS  (adapter per vendor, like the LLM layer)    │
│  Booking/PMS/POS · Calendar · Google Business · Payments   │
└──────────────────────────────────────────────────────────┘

        ▲                                   ▲
        │ live takeover / approvals         │ config, KB, analytics
┌──────────────────────────────────────────────────────────┐
│  STAFF CONSOLE (human-in-the-loop)  +  PLATFORM            │
│  auth · multi-tenant · queues · logging/eval · billing     │
└──────────────────────────────────────────────────────────┘
```

**The key idea:** every channel — voice included — collapses into the *same*
canonical text conversation before it reaches the brain. Voice is just text with
an audio codec + turn-taking layer in front. Build the brain once; reuse forever.

---

## 4. Channel layer (adapters)

Each channel is an adapter that (a) receives inbound events via webhook/stream,
(b) normalises to the canonical Message, (c) renders the brain's reply back in
that channel's format, and (d) handles that channel's rules (opt-in, windows,
templates). **The brain never knows which channel it's talking to.**

| Channel | Provider options | Notes / gotchas |
|---|---|---|
| **Voice (phone)** | Twilio Voice, Telnyx, Vonage (+ Media Streams over WebSocket) | Provision or port the business number, or forward their existing line after hours. Bidirectional audio streaming is the core primitive. |
| **SMS/MMS** | Twilio, Telnyx | US needs **A2P 10DLC** registration; international needs sender IDs. |
| **WhatsApp** | WhatsApp Business Platform (Meta Cloud API) or a BSP (360dialog, Twilio, MessageBird) | Requires a verified Meta Business + WABA. Outbound outside the **24-hour window** needs **pre-approved templates** + opt-in. Start via a BSP to skip infra pain. |
| **Instagram / Messenger** | Meta Messenger Platform / IG Messaging API | Same Meta app; page/IG-business linkage + permissions review. |
| **Web chat** | Our own widget (the one on the marketing site) over WebSocket | Fastest channel to ship; zero third-party approval. |
| **Email** | Postmark / SendGrid inbound parse + send | Good for slower enquiries and confirmations. |
| **Google reviews** | Google Business Profile API | Not a chat channel — a **poll/webhook → draft reply → staff approve → post** flow. |

> Ship order that minimises external approval friction: **Web chat → WhatsApp →
> SMS → Voice → IG/Messenger → Reviews.**

---

## 5. Voice pipeline — the one genuinely hard part

Voice needs sub-second responses and natural turn-taking (interruptions/barge-in).
Two architectures:

**A. Cascaded pipeline** — `STT → LLM(+tools) → TTS`
- STT: Deepgram / AssemblyAI / Whisper. TTS: ElevenLabs / Cartesia / Azure.
- **Pros:** full control, cheap, every turn is text we can log, guard, and reuse
  across channels; model-agnostic.
- **Cons:** you own turn-taking, VAD, barge-in, and latency budgeting (~800ms).

**B. Realtime speech-to-speech** — a single realtime voice model
- **Pros:** lowest latency, most natural, handles interruptions natively.
- **Cons:** newer, pricier, less transparent, harder to insert tool-calls +
  guardrails mid-turn, more vendor lock-in.

**DECISION (locked): we build the cascaded pipeline ourselves** on
`Twilio Media Streams → Deepgram (STT) → orchestrator → ElevenLabs/Cartesia (TTS)`.
We own turn-taking, VAD, barge-in, and the latency budget — more engineering, but
full control, lower unit cost, every turn is loggable text, and no runtime
lock-in. The voice front-end stays a **swappable module** so we can adopt realtime
speech-to-speech later without touching the brain.

**Why this is safe given "text-first" (§14):** we prove the entire brain — tools,
KB, guardrails, booking loop — in text *first*. By the time we build voice, the
hard "thinking" is already solved and battle-tested; the voice project reduces to
one focused problem: **the audio + turn-taking front-end feeding an already-proven
orchestrator.** That sequencing is what makes owning voice tractable for a small
team.

**Voice engineering checklist (Phase 1 sub-project):** bidirectional audio over
WebSocket · streaming STT with partials · endpointing/VAD · barge-in (cut TTS when
the caller speaks) · streaming LLM tokens into streaming TTS · ~800ms
response budget · warm/human transfer · voicemail fallback · call recording +
consent.

---

## 6. The orchestrator (the brain)

The stateful engine every message flows through. Responsibilities:

- **Session & state** — load/maintain conversation state per `conversationId`
  (Redis for hot state, Postgres for history); manage context-window budget.
- **Routing** — identify tenant, language, and intent; select the right
  agent/persona and toolset.
- **LLM orchestration** — an agent loop with **tool/function-calling**. System
  prompt = tenant brand voice + policies + guardrails.
- **RAG** — retrieve venue knowledge (menu, hours, rooms, FAQs, policies) from a
  vector store. **Authoritative live data (availability, prices) comes from tools,
  never RAG** — RAG answers "what/why", tools answer "is it actually free right now".
- **Guardrails** — allowed-actions whitelist; **confirm before any write**;
  ground every factual claim in KB/tool output (anti-hallucination); PII & abuse
  handling; refuse/deflect out-of-scope; hard stop → human on low confidence.
- **Turn-taking & latency** (voice) — streaming responses, interruption handling.

Frameworks: LangGraph or a small custom state machine. **Keep the LLM provider
abstraction that already exists in the repo** (`llm_service` + `providers/`) —
extend the same adapter pattern to telephony, messaging, and booking vendors.

---

## 7. Skills / tools (what the brain can *do*)

Each is a typed, validated function the LLM may call. Writes are guarded
(confirmation and/or staff approval per tenant config).

`KnowledgeLookup` · `CheckAvailability` · `CreateReservation` ·
`ModifyReservation` · `CancelReservation` · `PlaceOrder` · `GetGuestProfile` ·
`CreateLead` · `SendMessage/Confirmation` · `ScheduleCallback` ·
`DraftReviewReply` · `TransferToHuman` · `LogInteraction`

Design rules: idempotent writes (no double-bookings), every tool call logged with
inputs/outputs, and a dry-run/confirm step for anything that costs money or a table.

---

## 8. Integrations (adapter per vendor)

Same isolation pattern as the LLM layer — a stable interface, thin swappable
wrappers, so adding a POS = one new file.

- **Restaurants:** OpenTable / Resy / SevenRooms (reservations); Toast / Square
  (POS/orders).
- **Hotels:** Cloudbeds / Mews / Opera (PMS).
- **Calendar / fallback:** Google Calendar, and a **manual/Sheet-backed connector**
  so pilots can run before a deep POS integration exists.
- **Google Business Profile** — read reviews, post approved replies.
- **Notifications** — SMS / email / Slack / app push to reach staff.

Pilot with **one booking integration + the manual fallback**; expand by demand.

---

## 9. Human-in-the-loop (the trust layer)

Extend the existing dashboard into a staff console:
- **Live view + takeover** of any conversation (text) / warm transfer (voice).
- **Approvals queue** — pending reservations, review replies, outbound campaigns.
- **Knowledge editor** — hours, menu, policies, brand voice, escalation rules.
- **Analytics** — bookings captured, calls handled, deflection rate, response
  time, revenue recovered, CSAT.
- **Escalation rules** — complaint / VIP / low-confidence / explicit-ask → notify
  + route to a human.

---

## 10. Data model & memory

Multi-tenant Postgres + vector store + object store + Redis.

- `Tenant` → channels, config, brand voice, hours, rules
- `KnowledgeBase` (chunked + embedded) per tenant
- `Guest` → profile, preferences, history, **consent flags**
- `Conversation` → `Message[]` (any channel), state, language, transcripts, audio
- `Reservation` / `Order`
- `Action` / `Approval` (audit trail of every tool call + who approved)
- `User` (staff) + roles

Storage: **Postgres + pgvector** (relational + embeddings), **Redis** (session,
queues), **S3-compatible** object store (call recordings/transcripts).

---

## 11. Build vs buy — the leverage decisions

| Layer | Buy (fast) | Build (moat) | Recommendation |
|---|---|---|---|
| Telephony + STT/TTS + turn-taking | Vapi / Retell / LiveKit | Twilio + Deepgram + ElevenLabs, glued ourselves | **BUILD (locked)** — own it; keep the front-end swappable |
| WhatsApp infra | BSP (360dialog/Twilio) | Direct Meta Cloud API | **Buy** first, migrate later if margins demand |
| LLM | OpenAI / Anthropic / etc. | — | **Buy**, stay provider-agnostic (existing pattern) |
| **Orchestrator, tools, KB, guest memory, HITL console, integrations** | — | **Us** | **Build — this is the product.** |

Principle: rent everything commoditised; own everything that compounds into a moat
(the brain, the data, the workflow, the relationships).

---

## 12. Recommended stack

- **Backend:** Python + **FastAPI** (matches the repo; async for streaming). A
  small Node service is acceptable if a chosen voice runtime is JS-first.
- **Orchestration:** LangGraph or custom state machine; existing LLM abstraction.
- **Data:** Postgres + pgvector, Redis, S3-compatible store.
- **Realtime:** WebSockets for voice media + web chat.
- **Vendors (pilot):** Twilio (SMS/voice) or a voice runtime; WhatsApp via BSP;
  Deepgram (STT); ElevenLabs/Cartesia (TTS); OpenAI/Anthropic (LLM); pgvector (RAG).
- **Infra:** containers on Fly.io / Render / AWS with WebSocket support; queue
  (Redis/RabbitMQ) for event-driven resilience.

---

## 13. Non-functional requirements

- **Reliability:** event-driven + queued so a provider outage or traffic spike
  degrades gracefully (fall back to voicemail / "we'll text you back" / human).
- **Latency:** ~800ms voice response budget; stream tokens; pre-warm.
- **Observability:** trace every turn + tool call; an **eval harness** with
  scripted conversations to catch regressions; quality dashboards.
- **Security & compliance:** per-tenant isolation + encryption; **call-recording
  consent** (two-party-consent states); **GDPR/CCPA** (data export + delete);
  **WhatsApp opt-in + 24h window + template approval**; **A2P 10DLC/TCPA** for
  SMS; **PCI** avoidance — never store card data, use hosted/tokenised payments.

---

## 14. Phased roadmap

**Phase 0 — Foundations (text, one venue)**
Multi-tenant orchestrator + KB/RAG + guardrails + **web chat + WhatsApp text** +
`CheckAvailability`/`CreateReservation` (with manual/Sheet fallback) + staff
console with approvals. *Goal: prove the brain and the booking loop, safely.*

**Phase 1 — Add SMS + inbound voice (after-hours, self-built)**
SMS channel; **inbound voice on our own Twilio+Deepgram+TTS pipeline**, after-hours
only; outbound confirmations & reminders. This is where the voice-engineering
checklist (§5) gets built — against the brain already proven in Phase 0.
*Goal: recover the after-hours calls the site promises.*

**Phase 2 — Breadth**
Outbound voice (waitlist/reminders); IG/Messenger; **Google review drafting**;
upsell; multilingual; first deep POS/PMS integration; analytics.

**Phase 3 — Depth & scale**
Realtime speech-to-speech (if volume justifies); richer personalization; proactive
campaigns; self-serve onboarding; connector marketplace.

**Pilot strategy:** one venue, **text + after-hours voice**, humans approving all
writes, measuring **recovered bookings & calls** against a real baseline — the
exact promise the website makes.

---

## 15. Decisions

1. ✅ **LOCKED — Voice: build it** on Twilio Media Streams + Deepgram + TTS
   (cascaded pipeline we own; front-end swappable). See §5.
2. ✅ **LOCKED — Pilot: text-first, one venue.** Web chat + WhatsApp text +
   reservations + staff approvals prove the booking loop before any phone line;
   self-built voice follows in Phase 1 against the already-proven brain.
3. **Open — First booking integration:** which POS/PMS, or manual/Sheet fallback
   only for the pilot?
4. **Open — Pilot venue:** the Graycliff-style profile, or hold for a real signed
   pilot first?
5. **Open — Hosting & data region** (drives compliance choices).

---

## 16. Top risks & mitigations

| Risk | Mitigation |
|---|---|
| Voice latency/quality feels robotic | Buy a proven runtime; strict latency budget; barge-in; human fallback |
| Hallucinated hours/prices/policies | Ground every fact in KB/tools; confirm writes; refuse when unsure |
| WhatsApp/SMS compliance blocks launch | Start web chat (no approval); begin Meta/A2P registration early in parallel |
| Double-bookings / bad writes | Idempotent tools; approval queue; dry-run + confirm |
| Integration sprawl | Adapter pattern + manual fallback; add connectors only on demand |
| Trust ("will it embarrass us?") | Human-in-the-loop default; after-hours-only start; visible guardrails |
```
