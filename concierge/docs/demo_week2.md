# Week 2 Demo — the full booking loop (check → draft → **staff-approve** → confirm)

*Day 14 deliverable (W2-D14-1). This is the scripted end-to-end walkthrough that
proves the Week-2 "definition of done": a guest books, a **Request** appears in the
staff queue, a human **approves**, and only then is the reservation written and the
guest confirmed — nothing hits the booking store without a human.*

Everything below is runnable against the local stack.

---

## 0 · Prerequisites

```bash
cd concierge
docker compose up -d db redis          # Postgres 16 + pgvector, Redis (already up in dev)
./.venv/bin/alembic upgrade head       # schema
./.venv/bin/python scripts/seed.py     # demo tenant (slug: demo) + channels
./.venv/bin/python scripts/ingest_kb.py   # load the demo venue's hours/menu/policies
./.venv/bin/uvicorn app.main:app --reload
```

Two dev surfaces are mounted in dev only:
- **`GET /dev/chat`** — type to the concierge (the guest's view)
- **`GET /dev/approvals`** — the staff queue (approve / reject)

Staff API auth is the stopgap `X-Staff-Token` header (default `dev-token`) — **real
auth is Day 24**; documented loudly in `app/routers/approvals.py`.

---

## 1 · Grounded Q&A (Week-1 foundation, still true)

In `/dev/chat`:

> **Guest:** what time do you open on Friday?
> **Concierge:** *(grounded from the KB)* We're open Friday 12pm–midnight…

> **Guest:** do you have vegan mains?
> **Concierge:** *(grounded)* Yes — e.g. …

> **Guest:** do you validate parking downtown? *(not in the KB)*
> **Concierge:** I don't have that detail to hand — I'll check with the team and
> follow up. *(no invention — the grounding floor at work)*

---

## 2 · The booking — check → confirm-back → draft

> **Guest:** can I get a table for 4 this Friday at 8pm?
> **Concierge:** *(calls `check_availability`)* 8:00 is fully booked — I have **8:30**
> open. Shall I put in a request for a table of 4 at 8:30 Friday?  ← **confirm-back before any write**

> **Guest:** yes please
> **Concierge:** *(calls `draft_reservation`)* Done — I've sent that to the team to
> confirm. You'll hear back shortly.

**What just happened underneath:** `draft_reservation` (a `draft`-kind tool) created a
**`Request(type=reservation, status=needs_review)`** — and **no `Reservation` row**.
Prove it:

```bash
# psql — a pending Request exists…
docker compose exec db psql -U concierge -c \
  "select type,status,summary,confidence from requests order by created_at desc limit 1;"
#  reservation | needs_review | Table for 4 on 2026-07-31 at 20:30 | 0.95

# …and NO reservation yet
docker compose exec db psql -U concierge -c "select count(*) from reservations;"
#  0
```

The guest was **not** told "confirmed" — only "sent to the team."

---

## 3 · The staff queue

```bash
curl -s localhost:8000/api/approvals -H "X-Staff-Token: dev-token" | jq
```
```json
{ "total": 1,
  "requests": [{
    "request_id": "…", "type": "reservation", "status": "needs_review",
    "summary": "Table for 4 on 2026-07-31 at 20:30", "priority": "normal",
    "confidence": 0.95, "created_at": "…" }]}
```

Or open **`/dev/approvals`** — the one-line summary + Approve/Reject, exactly the
"needs your attention" screen from the Week-2 designer mock.

---

## 4 · Approve → fulfilment writes the booking → guest confirmed

```bash
curl -s -X POST localhost:8000/api/approvals/decide \
  -H "X-Staff-Token: dev-token" -H "content-type: application/json" \
  -d '{"request_id":"<id from step 3>","decision":"approved","note":"window table"}' | jq
```

On approval the fulfilment worker runs the **only** write path
(`create_reservation`, a `fulfilment`-kind tool never exposed to the LLM):

```bash
# a confirmed reservation now exists…
docker compose exec db psql -U concierge -c \
  "select party_size,date,time,status from reservations order by created_at desc limit 1;"
#  4 | 2026-07-31 | 20:30:00 | confirmed

# …the Request is completed…
docker compose exec db psql -U concierge -c \
  "select status from requests order by created_at desc limit 1;"
#  completed
```

- **Reservation(confirmed)** in Postgres (+ mirrored to the Google Sheet if `SHEET_ID` set)
- **`Request(completed)`**, with an append-only **`Approval`** row recording
  `decided_by` / `decided_at`
- a confirmation message written back into the guest's conversation

**Reject** instead → `Request(rejected)`, a polite guest message, **no artifact written**.

---

## 5 · The wedge — an off-tool message still becomes structured work

This is the moment a venue owner "gets it":

> **Guest:** can I book the private terrace for 30 people in December?

No `draft_*` tool covers this. After the turn, the **extractor** (post-turn fallback
classifier) opens a **`Request(type=other, priority=high, needs_review)`** so the most
valuable message of the week lands in the same queue instead of being answered politely
and vanishing.

```bash
curl -s localhost:8000/api/approvals -H "X-Staff-Token: dev-token" | jq '.requests[].type'
#  "other"   ← captured, queued, not dropped
```

---

## What this demo proves (the Week-2 definition of done)

| Claim | Shown in |
|---|---|
| Grounded answers, no invention | §1 |
| Checks availability + confirms back before writing | §2 |
| A booking becomes a **Request**, not a silent reservation | §2 |
| **Nothing is written without a human approval** | §2 → §4 |
| Fulfilment is the *only* write path; guest confirmed after approval | §4 |
| Full audit trail (Approval: who/when) | §4 |
| Off-tool asks are captured, not lost | §5 |

## Known stopgaps (by design, scheduled later)
- Staff auth = `X-Staff-Token` shared secret → **Day 24** (real auth + RBAC).
- `GET /api/approvals` is not yet tenant-scoped in the query → tighten with real auth (Day 24); fine for the single-tenant pilot.
- WhatsApp channel → **Week 3 / Day 15**; staff console UI → **Days 17–20** (this API is what it renders).
