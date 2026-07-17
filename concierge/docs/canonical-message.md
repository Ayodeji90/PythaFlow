# The Canonical Message contract

The single most important interface in the concierge. Everything else hangs off it.

## Why it exists

A concierge has to answer guests on web chat, WhatsApp, SMS, Instagram — and
eventually the phone. If each channel talked to the brain in its own dialect, the
brain would grow a branch per channel and adding the sixth would touch everything.

So we invert it: **every channel normalises into one canonical message before the
brain sees it.** The orchestrator has no idea whether a guest is on WhatsApp or a
web page. Voice, later, is the same trick — audio becomes text at the edge, and
the brain never learns it was a phone call.

That's the claim Day 15 tests: adding WhatsApp should need **zero brain changes**.

## The two types (`app/schemas/message.py`)

These are **wire/in-flight DTOs** (pydantic), deliberately separate from the
persisted `app.models.Message` row (SQLAlchemy). The transport contract must not
be coupled to storage.

### `InboundMessage` — what every channel produces

| Field | Meaning |
|---|---|
| `tenant_slug` | which business this is for |
| `channel` | `webchat` \| `whatsapp` \| `sms` \| `voice` \| … |
| `conversation_ref` | the channel's own thread id → resolved to a `Conversation` via the `(tenant_id, external_thread_id)` index |
| `sender` | `SenderRef(id, name?, phone?, handle?)` — channel-neutral identity |
| `content` | the text |
| `content_type` | `text` \| `audio` |
| `locale` | detected/declared language, if any |
| `received_at` | timestamp |
| `metadata` | escape hatch for channel extras (e.g. a WhatsApp message id) |

### `OutboundChunk` — what the orchestrator streams back

| `type` | Meaning |
|---|---|
| `typing` | hint the channel may render as a typing indicator |
| `token` | a streamed fragment (Day 4) — concatenate them |
| `message` | one complete message |
| `action` | a tool/side-effect notification (Day 8+) |
| `done` | the turn is finished |
| `error` | something failed; `content` explains |

Streaming (`AsyncIterator[OutboundChunk]`) exists from Day 3 even though the echo
has nothing to stream — so Day 4's token streaming needs no interface change.

## The flow

```
provider payload
      │  adapter.to_inbound()          ← the ONLY channel-specific code
      ▼
InboundMessage ──▶ handle_inbound()    ← shared pipeline (channels/base.py)
                     ├─ resolve tenant (slug → Tenant)
                     ├─ resolve/create Conversation  (tenant_id, external_thread_id)
                     ├─ persist the guest turn        (role=guest)
                     ├─ orchestrator.handle(...)  ──▶ yields OutboundChunks
                     └─ persist the assistant turn    (role=assistant)
      │
      ▼
OutboundChunk stream ──▶ channel renders it (web chat: JSON frames over the socket)
```

The guest turn is committed **before** the orchestrator runs, so a failure mid-think
never loses what the guest said.

## Adding a channel (the Day-15 shape)

1. Write `app/channels/<name>.py` with a `to_inbound()` that maps the provider's
   payload onto `InboundMessage`.
2. Add a router that receives the provider's webhook and calls `handle_inbound()`.
3. Render `OutboundChunk`s back in that provider's format.

**Nothing in `orchestrator/`, `models/`, or the pipeline changes.** If it does,
the abstraction leaked and that's the bug.

## Current endpoints (web chat)

| Endpoint | Purpose |
|---|---|
| `WS /ws/chat?tenant=<slug>&conversation=<ref>` | send `{"content": "..."}`, receive `OutboundChunk` JSON frames |
| `POST /api/chat` | non-streaming fallback: `{tenant, content, conversation_ref?}` → `{conversation_ref, reply}` |
| `GET /dev/chat` | dev-only manual test page (not mounted outside dev) |
