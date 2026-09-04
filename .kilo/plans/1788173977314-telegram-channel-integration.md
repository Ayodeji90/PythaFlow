# Plan: Telegram Channel Integration for Balance Concierge

> **Status: IMPLEMENTED (commit `9fcacff` + follow-up)**
> **Revision note (D1 flip):** The original plan selected **MTProto** (per user request). During review of the landed code this was reversed to **Bot API only** — the implementation had inherited both halves of a contradiction: inbound arrived as a Bot API webhook (guest messages `@VenueBot`), but outbound sent via an MTProto *user-account* session. A bot and a user account are two different Telegram identities, so replies could never be delivered into the guest's chat with the bot. The fix (confirmed with the user: *Bot API only*) deletes that identity mismatch, drops `telethon`, and makes the channel structurally identical to WhatsApp/Twilio. Sections D1, D2, D4, D10–D12, the task list, data flow, failure modes, dependencies, and rollout below reflect the **final, shipped** design.

## Goal
Add Telegram as a supported guest channel alongside WhatsApp, WebChat, and Email — using the existing channel adapter pattern so the orchestrator, tools, RAG, approvals, and guardrails require zero changes.

---

## Current Architecture Context

**Channel Adapter Pattern** (established in `app/channels/`):
- Each channel provides: `Adapter.to_inbound()` + `Client` Protocol + `Router`
- Shared pipeline in `base.py:handle_inbound()` handles: tenant resolution → conversation threading → guest memory → orchestrator → persist → outbound
- Orchestrator is completely channel-agnostic

**Existing Channels**:
| Channel | Adapter | Client | Router | Thread Key |
|---------|---------|--------|--------|------------|
| WebChat | `WebChatAdapter` | N/A (JSON is wire) | `webchat.py` | browser session ID |
| WhatsApp | `WhatsAppAdapter` | `TwilioWhatsAppClient` | `whatsapp.py` | `WaId` (phone) |
| Email | `EmailAdapter` | `SmtpSender` | `email.py` | `Message-ID` / `In-Reply-To` |
| **Telegram** | `TelegramAdapter` | `BotApiTelegramClient` | `channels/telegram/router.py` | `chat_id` |

**ChannelType enum** (`models/enums.py`): now includes `telegram = "telegram"`.

---

## Design Decisions (Final)

### D1: Bot API vs MTProto — **RESOLVED: Bot API only** (reversed from original MTProto pick)
**Question**: Use Telegram Bot API (HTTPS, simple) or MTProto (raw, full client)?

| Option | Merits | Demerits |
|--------|--------|----------|
| **Bot API** (Selected) | ✅ Simple HTTP/JSON interface<br>✅ One credential: a bot token from @BotFather (2 min setup, no phone/login/session)<br>✅ Matches existing WhatsApp/Twilio pattern (plain HTTPS POST via httpx)<br>✅ One identity end-to-end: guest messages bot → same bot replies<br>✅ Easy to test/mock (httpx MockTransport) | ❌ Limited to bot capabilities (no user-account features)<br>❌ Rate limits apply (mitigated by 429 `Retry-After` handling) |
| **MTProto** (Rejected) | ✅ Full client capabilities / can act as a user account | ❌ **Identity mismatch**: a Bot-API inbound webhook answers from a user session — Telegram won't deliver a user's message into a bot's chat, so replies never reach the guest<br>❌ Requires the venue owner to hand over a personal Telegram login; violates Telegram ToS (userbots)<br>❌ Interactive auth flow (`input()` on stdin) hangs forever in a container<br>❌ Session management, native dep (`telethon`), much harder to test |

**Final decision**: **Bot API for everything.** Outbound is `POST https://api.telegram.org/bot<TOKEN>/sendMessage` over httpx — the bot the guest messaged is the bot that replies. The MTProto/Telethon client, parser, and stdin auth were **deleted**; `telethon` never entered `uv.lock`.

### D2: Webhook vs Long Polling — **RESOLVED: Webhook only** (+ tunnel for local dev)
| Option | Merits | Demerits |
|--------|--------|----------|
| **Webhook** (Selected) | ✅ Matches WhatsApp pattern exactly; scales horizontally<br>✅ Low latency; no polling overhead<br>✅ `X-Telegram-Bot-Api-Secret-Token` header auth | ❌ Needs a public URL (tunnel for dev, e.g. ngrok/cloudflared) |
| **Long Polling** (Rejected) | ✅ Works locally without public URL | ❌ Single-process; doesn't scale; extra update-source loop to maintain |

**Final decision**: **Webhook only.** Inbound is the single update source; `setWebhook`/`deleteWebhook` helpers exist on the router. Local dev uses a tunnel to the public URL. (The original "fall back to long polling when `TELEGRAM_WEBHOOK_URL` is empty" idea was dropped — no polling loop exists and no `TELEGRAM_WEBHOOK_URL` setting was kept.)

### D3: Thread Key — `chat_id` — **RESOLVED: `chat_id`** (unchanged)
- Private chat: `chat_id == user_id` (1:1), matching WhatsApp's `WaId`.
- Stable thread key: `conversation_ref = str(chat_id)`.

### D4: Tenant Routing — **RESOLVED: Single bot per tenant + per-tenant webhook path**
| Option | Final choice |
|--------|-------------|
| **A/B. external_id lookups / shared bot with mapping** | Rejected — ambiguity or extra routing logic |
| **C. Single bot per tenant** (Selected) | Each venue has its own branded bot (`@venuebot`). Token + webhook secret live in the venue's `Channel.config` (`bot_token`, `webhook_secret`); bot @username persisted to `Channel.external_id` via `getMe`. |
| **D. Shared bot + default-tenant fallback** | Kept only as the **sandbox path**: shared `POST /webhooks/telegram` routes to `TELEGRAM_DEFAULT_TENANT`. |

**Routing mechanism (final)**: the **webhook URL path identifies the tenant** — each bot is registered at `POST /webhooks/telegram/{tenant_slug}` (this also gives per-channel webhook secret validation). This replaces the original plan's loose "look up any active Telegram `Channel` row" idea, which silently collapsed every venue to one tenant. The shared path (`/webhooks/telegram`) is the dev/sandbox convenience and 404s/discards when no default tenant is set.

### D5: Media Handling — **RESOLVED: Phase 1 text only** (unchanged)
Text-only MVP; images/docs Phase 2 (Bot API `getFile` → download); voice deferred (STT is separate effort).

### D6: 24-Hour Window Difference — **RESOLVED: No template restriction** (unchanged)
Telegram is always free-form — always `sendMessage`, no template approval flow.

### D7: Authentication / Webhook Verification — **RESOLVED: Secret token header, per channel**
- `X-Telegram-Bot-Api-Secret-Token` validated against `Channel.config["webhook_secret"]`, falling back to the global `TELEGRAM_WEBHOOK_SECRET` env var.
- No secret configured anywhere → dev mode (accept but log a warning loudly).
- Set during webhook registration via the `/set` helper (`setWebhook?secret_token=`).

### D8: Callback Queries (Inline Buttons) — **RESOLVED: Defer to Phase 2** (unchanged)
Text commands ("APPROVE #123") for MVP; staff approvals already have a web UI. Callback queries add a second update type to the router.

### D9: Group/Channel Support — **RESOLVED: Private chats only, enforced in the adapter** (unchanged)
`TelegramInbound.from_webhook_update()` returns `None` for non-`private` chat types and non-text messages; `is_private` is a real property over the stored `chat_type` (no longer a hardcoded `True`).

### D10–D12 (MTProto-specific) — **SUPERSEDED / MOOT**
These original open questions existed *because* of MTProto and are obsolete under Bot API:
- **D10 (shared vs per-tenant API ID/Hash)** → n/a. Each venue's credential is a **bot token** from @BotFather, stored in `Channel.config["bot_token"]` — no my.telegram.org app registration.
- **D11 (phone number management)** → n/a. Bot accounts have no phone number and no SMS/call auth.
- **D12 (session storage)** → n/a. Stateless: every send is a fresh HTTPS POST authenticated by the token. Nothing to encrypt, back up, or refresh — no session expiry failure mode.

---

## Implementation (as shipped)

### Files

```
concierge/app/channels/telegram/
├── __init__.py              # exports (TelegramAdapter, clients, send_with_retry, router)
├── adapter.py               # TelegramInbound + TelegramAdapter
├── client.py                # TelegramClient ABC, BotApiTelegramClient, NullTelegramClient,
│                            #   build_telegram_client, send_with_retry (429-aware)
└── router.py                # /webhooks/telegram[/{tenant_slug}|/set|/delete]
```

| File | Change |
|------|--------|
| `app/models/enums.py` | `telegram = "telegram"` added to `ChannelType` |
| `app/config.py` | **2** env vars only: `TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_DEFAULT_TENANT` (MTProto envs and `TELEGRAM_WEBHOOK_URL` removed) |
| `app/main.py` | Import & include `telegram.router` |
| `app/channels/telegram/router.py` | Also serves as the mount point (mirrors how WhatsApp's router is mounted) |
| `scripts/seed.py` | `TELEGRAM_BOT_TOKEN` env provisions the demo tenant's Telegram `Channel` row (idempotent) |
| `alembic/versions/a6f2b1c3d4e5_add_telegram_channel_type.py` | Migration adding `telegram` to `channel_type` enum CHECKs where present |
| `alembic/versions/b7e4d5f6a1c2_add_tenants_voice_config.py` | (found en route) migration for the earlier `Tenant.voice_config` model change |
| `pyproject.toml` | **No new runtime deps** — `telethon` never added; outbound uses existing `httpx` |

### Client (`client.py`) — Bot API outbound
- `BotApiTelegramClient.send_text()` → `POST api.telegram.org/bot<TOKEN>/sendMessage` (`chat_id`, `text`).
- Replies > 4096 chars split into multiple messages (message ids joined and returned).
- `send_with_retry()` wrapper: exponential backoff (3 attempts), **429 respects `Retry-After`** (capped at 60s); only failed attempts retried (never duplicates a successful send); raises loudly after exhaustion.
- `NullTelegramClient` fallback logs instead of sending when no token is configured; `build_telegram_client(token)` picks based on the venue's token.

### Router (`router.py`) — inbound + webhook lifecycle
```
Guest → @VenueBot → Telegram → POST /webhooks/telegram/{tenant_slug} (Bot API webhook)
  → TelegramInbound.from_webhook_update()   (text + private chat only, else ack-ignore)
  → Redis dedup tg:seen:{update_id} (NX, 1h TTL)   [skips Telegram retries; WhatsApp wa:seen pattern]
  → tenant from URL path slug (or TELEGRAM_DEFAULT_TENANT on the shared path)
  → per-channel webhook-secret check (403 on mismatch)
  → TelegramAdapter.to_inbound() → InboundMessage (conversation_ref = str(chat_id))
  → base.handle_inbound()  (THE shared pipeline — orchestrator/tools/RAG/approvals untouched)
  → reply sent via the SAME channel's bot_token  (one identity end-to-end)
```
Routes (registered in this order — the `{tenant_slug}` catch-all comes **after** the literal `/set`/`/delete` so it can't shadow them):
- `GET  /webhooks/telegram` → health check
- `POST /webhooks/telegram` → sandbox; routes to `TELEGRAM_DEFAULT_TENANT`
- `POST /webhooks/telegram/set` → body `{tenant_slug, url}`; calls Bot API `setWebhook` with the per-tenant URL + secret token (`allowed_updates: [message, edited_message]`), persists bot @username from `getMe` to `Channel.external_id`
- `POST /webhooks/telegram/delete` → body `{tenant_slug}`; calls `deleteWebhook`
- `POST /webhooks/telegram/{tenant_slug}` → per-tenant inbound

### Adapter (`adapter.py`) — inbound normalization
- `TelegramInbound.from_webhook_update()` parses `message`/`edited_message`; returns `None` for non-text or non-private chats.
- `TelegramAdapter.to_inbound()` → canonical `InboundMessage` (`channel=telegram`, `conversation_ref=str(chat_id)`, sender from `from`, Telegram metadata preserved).

### Config surface
| Setting | Purpose |
|---------|---------|
| `TELEGRAM_WEBHOOK_SECRET` | Global fallback secret (used when a channel row has no `webhook_secret`) |
| `TELEGRAM_DEFAULT_TENANT` | Slug for the shared sandbox webhook path; empty → unknown-tenant updates are discarded (no `AttributeError` — defined in config) |
| `Channel.config["bot_token"]` | The venue's bot token (outbound + webhook registration) |
| `Channel.config["webhook_secret"]` | The venue's per-bot secret (overrides the env fallback) |
| `Channel.external_id` | Bot @username (set by `/set` via `getMe`) |

### Migration note (verified against live Postgres)
The alembic migrations render the enum columns as plain `VARCHAR(32)` **without CHECK constraints** — inserting a `telegram` row already works, so `a6f2b1c3d4e5` is a **defensive no-op** that only extends enum CHECKs on DBs that have them (e.g. `create_all`-built dev DBs). Tested upgrade → downgrade → upgrade cleanly. En route, a real pre-existing gap was found and fixed: `Tenant.voice_config` (from the D2 voice-schema work) was on the model but never migrated — `b7e4d5f6a1c2` adds it (any tenant INSERT on a migrated DB would otherwise fail).

---

## Task List (status at implementation)

#### Phase 1: Core Channel (MVP — Text Only) — ✅ DONE
- [x] **T1** Add `telegram` to `ChannelType` enum
- [x] **T2** Create `app/channels/telegram/adapter.py` — `TelegramInbound` + `from_webhook_update()` (text + private-chat guard), `TelegramAdapter.to_inbound()`
- [x] **T3** Create `app/channels/telegram/client.py` — **`BotApiTelegramClient`** (httpx POST to Bot API), 4096-char split, `NullTelegramClient`, `build_telegram_client()`. *(Replaces the original `TelegramMTProtoClient`/Telethon task.)*
- [x] **T4** Create `app/channels/telegram/router.py` — health, per-tenant + shared inbound, `/set` + `/delete` webhook helpers
- [x] **T5** Add config: `TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_DEFAULT_TENANT` (per-tenant secrets/tokens live in `Channel.config`)
- [x] **T6** Register router in `app/main.py`
- [x] **T7** Migration for `ChannelType` (`a6f2b1c3d4e5` — defensive no-op; schema is unconstrained VARCHAR, verified live)
- [x] **T8** Unit tests — `tests/test_telegram_router.py`, `tests/test_telegram_adapter.py`, `tests/test_telegram_client.py` (21 tests)

#### Phase 2: Media & Rich Features — ⬜ FUTURE
- [ ] **T9** Extend adapter: parse `photo`, `document`, `location`, `contact` from Bot API updates
- [ ] **T10** Extend client: `send_photo`, `send_document`, `send_location`
- [ ] **T11** Media download via Bot API `getFile` → store → RAG ingestion

#### Phase 3: Operational Hardening — ✅ (MVP items shipped)
- [x] **T12** Deduplication: Redis `tg:seen:{update_id}` (like WhatsApp `wa:seen`)
- [x] **T13** Retry logic: `send_with_retry` with exponential backoff + 429 `Retry-After` handling
- [ ] **T14** (n/a for Bot API) — Bot API rate limits handled per-request via 429 backoff
- [ ] **T15** Webhook secret rotation endpoint (rotate by editing `Channel.config["webhook_secret"]` + re-running `/set`)
- [ ] **T16** (n/a for Bot API) — no sessions to expire/refresh; token rotation = new token + re-run `/set`

#### Phase 4: Multi-Tenant Polish — ✅ (core shipped)
- [x] **T17** Per-tenant bots: per-venue `bot_token` + `webhook_secret` in `Channel.config`, per-tenant webhook path
- [ ] **T18** Staff approval via callback queries (inline "Approve/Reject" buttons) — deferred

---

## Data Flow (MVP, as shipped)

```
Guest → @VenueBot (Telegram) → Bot API webhook POST
          ↓
/webhooks/telegram/{tenant_slug} (FastAPI)
          ↓
validate X-Telegram-Bot-Api-Secret-Token (per-channel secret, env fallback)
          ↓
TelegramInbound.from_webhook_update()  (text + private chat only)
          ↓
Redis dedup  tg:seen:{update_id}
          ↓
tenant from URL path (or TELEGRAM_DEFAULT_TENANT on shared path)
          ↓
TelegramAdapter.to_inbound() → InboundMessage (conversation_ref = str(chat_id))
          ↓
base.handle_inbound() → orchestrator → tools → RAG → reply chunks
          ↓
BotApiTelegramClient.send_text(chat_id, reply)   // POST /bot<TOKEN>/sendMessage
          ↓
Guest receives reply from @VenueBot — the same bot they messaged
```

---

## Failure Modes & Mitigations (as shipped)

| Failure | Detection | Mitigation |
|---------|-----------|------------|
| Invalid/missing webhook secret | 403 (or dev-mode warning) | Per-channel secret; `/set` rotates; attempts logged |
| Unknown tenant on shared path | "No tenant … discarding" log | Discard + return 200; configure `TELEGRAM_DEFAULT_TENANT` or use per-tenant path |
| Duplicate update (Telegram retry) | Redis `tg:seen:{update_id}` exists | Skip processing; return 200 |
| Rate limited (HTTP 429) | `Retry-After` header | `send_with_retry` sleeps (capped 60s), retries up to 3× |
| Transient send failure (network/5xx) | httpx exception | Exponential backoff retry; raises loudly after last attempt (never silent) |
| Reply > 4096 chars | local length check | Chunked into multiple `sendMessage` calls |
| Group/channel/edited-non-text update | `chat.type != "private"` / no `text` | Acknowledge + ignore in adapter |
| Redis down (dedup) | exception on `set` | Best-effort: log warning, process anyway |
| Bot token missing / wrong | 400 from `/set` or outbound failure | `NullTelegramClient` logs instead of sending in dev; loud log in prod |
| No bot_token on Channel row | `/set` returns 400 "Bot token not configured" | Provision via seed (`TELEGRAM_BOT_TOKEN`) or set `Channel.config["bot_token"]` |

---

## Validation (as run)

### Unit Tests (✅ 21 tests, all green)
- `test_telegram_adapter.py` — `from_webhook_update` parses text/edited, rejects non-private chats & non-text
- `test_telegram_client.py` — Bot API URL/payload shape, 4096-char splitting, `NullTelegramClient`, retry on 429/transient errors
- `test_telegram_router.py` (DB-backed) — per-tenant isolation (two venues → each replies with its **own** bot token), webhook-secret 403s, Redis dedup, private-chat guard, unknown-tenant discard, `/set` + `/delete` helpers

### Integration / Verification (✅ run against live docker db + redis)
- Alembic upgrade → downgrade → upgrade clean (`a6f2b1c3d4e5`, then `b7e4d5f6a1c2`)
- `create_all`-style DB path (CHECK exists without `telegram`) — constraint extended, name preserved
- **Full suite: 177 passed, 0 failed** (previously 106 passed / 50 DB-connection errors without the stack up)

### Manual Verification (pilot)
1. Create a bot via `@BotFather`, put its token in `Channel.config["bot_token"]` (or set `TELEGRAM_BOT_TOKEN` and run `scripts/seed.py`)
2. Set a per-channel `webhook_secret` (or rely on `TELEGRAM_WEBHOOK_SECRET`)
3. Register the webhook: `POST /webhooks/telegram/set` with `{tenant_slug, url}` (tunnel for local dev) — this also stores the bot @username
4. Message the bot → verify the concierge replies from the **same bot**
5. Check the conversation in the staff console

---

## Rollout Strategy (as shipped)

1. **Local Dev**: seed the tenant's Telegram `Channel` row; point a tunnel at the API; register via `/set`; send a message to the bot.
2. **Staging**: shared webhook domain; each tenant registers its own bot at `/webhooks/telegram/{slug}`; `TELEGRAM_DEFAULT_TENANT` set for the sandbox path.
3. **Production Pilot**: one bot per venue (`Channel.config["bot_token"]` + `webhook_secret`), per-tenant webhook paths, secret tokens on every webhook.
4. **Future**: callback-query approval buttons, media, group support — all additive on the Bot API.

---

## Dependencies

- **New runtime deps**: **none** — outbound is existing `httpx`. (`telethon` was considered and dropped.)
- **Existing deps**: `httpx`, `redis` (dedup), existing DB models.
- **Database migration**: `a6f2b1c3d4e5` (defensive enum-CHECK no-op) + `b7e4d5f6a1c2` (`tenants.voice_config` gap fix).
- **Config**: 2 env vars (`TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_DEFAULT_TENANT`); per-venue `bot_token` / `webhook_secret` in `Channel.config`.

---

## Out of Scope (Explicit)

- Voice message transcription (requires STT service)
- Inline mode / `@bot` queries in other chats
- Telegram Stars / payments
- Bot API 7.0+ features (business messages, reactions) — evaluate later
- Group/channel conversations (MVP is private 1:1 chats only)
