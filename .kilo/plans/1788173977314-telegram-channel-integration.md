# Plan: Telegram Channel Integration for Balance Concierge

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

**ChannelType enum** (`models/enums.py:16-22`): `webchat`, `whatsapp`, `sms`, `voice`, `instagram`, `email` — **Telegram missing**

---

## Design Decisions Required

### D1: Bot API vs MTProto
**Question**: Use Telegram Bot API (HTTPS, simple) or MTProto (raw, full client)?

| Option | Merits | Demerits |
|--------|--------|----------|
| **Bot API** | ✅ Simple HTTP/JSON interface<br>✅ No session/state management<br>✅ Works behind any HTTP proxy/firewall<br>✅ Matches existing WhatsApp/Twilio pattern<br>✅ No additional native deps (uses existing httpx)<br>✅ Easy to test/mock<br>✅ Handles media via getFile + download | ❌ Limited to bot capabilities (cannot join groups as normal user)<br>❌ Some advanced features unavailable (e.g., reading all messages in large groups)<br>❌ Rate limits apply (30 msg/sec) |
| **MTProto** (Selected) | ✅ Full Telegram client capabilities<br>✅ Can join groups/channels as regular user<br>✅ Access to all messages (no bot limitations)<br>✅ No rate limits for receiving<br>✅ More authentic Telegram experience<br>✅ Can work as user account (not just bot)<br>✅ Better for group interactions | ❌ Complex binary protocol implementation<br>❌ Requires session management, encryption, auth flow<br>❌ Native dependencies (telethon or similar)<br>❌ Firewall/proxy complications<br>❌ Overkill for simple concierge use case<br>❌ Significantly more complex to test/mock<br>❌ Requires handling user login/session<br>❌ More privacy considerations (access to full account) |

**Recommendation**: **MTProto** — selected per user request for full Telegram capabilities despite increased complexity.

**Rationale**:
- User specifically requested MTProto for access to advanced Telegram features
- Enables joining groups/channels as regular user (not limited to bot capabilities)
- Access to all messages without bot restrictions
- No rate limits for receiving messages
- More authentic Telegram experience that can work as a user account

### D2: Webhook vs Long Polling
**Question**: How does the bot receive updates?

| Option | Merits | Demerits |
|--------|--------|----------|
| **Webhook** (Recommended for production) | ✅ Matches WhatsApp pattern exactly<br>✅ Scales horizontally (multiple instances behind LB)<br>✅ Low latency delivery<br>✅ No polling overhead<br>✅ Works with existing async pipeline<br>✅ Production-ready pattern | ❌ Requires publicly accessible URL (needs domain, SSL, port 443)<br>❌ More complex local development (requires ngrok or similar)<br>❌ Webhook URL must be configured via BotFather |
| **Long Polling** (Recommended for local dev) | ✅ Works locally without public URL<br>✅ Simple to set up (no webhook config needed)<br>✅ Good for development/testing<br>✅ No external dependencies | ❌ Does not scale (single process holds connection)<br>❌ Higher latency (up to 30s timeout)<br>❌ Keeps HTTP connection open constantly<br>❌ Not suitable for production deployment<br>❌ Can interfere with hot-reload in development |

**Recommendation**: **Webhook** (production) + **Long Polling** (local dev only)

**Rationale**:
- Webhook: matches WhatsApp pattern, scales, works with existing `handle_inbound` pipeline
- Long polling: useful for `uv run uvicorn --reload` without ngrok
- Implementation: router handles both; webhook is default when `TELEGRAM_WEBHOOK_URL` set, falls back to polling when empty

### D3: Thread Key — `chat_id` or `user_id`?
**Question**: What identifies a conversation thread?

| Option | Merits | Demerits |
|--------|--------|----------|
| **chat_id** (Recommended) | ✅ Unique per chat (1:1, group, channel)<br>✅ Matches WhatsApp pattern (`WaId` identifies contact/chat)<br>✅ Groups multiple users under one thread (venue talks to group as entity)<br>✅ Stable for the lifetime of the chat<br>✅ Works with Email-like threading model | ❌ In group chats, cannot distinguish individual users<br>❌ Requires storing chat_id for each conversation |
| **user_id** | ✅ Identifies specific individual<br>✅ Enables personalization per user in groups<br>✅ Matches some mental models of "user conversation" | ❌ Breaks for group chats (multiple users, same bot)<br>❌ No stable thread for group conversations<br>❌ Inconsistent with WhatsApp/Email models<br>❌ Requires complex mapping for group use cases |
| **message_id** | ✅ Unique per message<br>✅ Simple to implement | ❌ Changes every message - no thread continuity<br>❌ Cannot maintain conversation state<br>❌ Breaks guest memory/context across turns<br>❌ Not usable for threading |

**Recommendation**: **`chat_id`** (not `user_id`)

**Rationale**:
- Private chat: `chat_id == user_id` (1:1)
- Group/channel: `chat_id != user_id` — multiple users share one thread
- Concierge is venue-facing: one conversation per guest contact point
- Matches WhatsApp (`WaId` = contact) and Email (`Message-ID` = thread)

### D4: Tenant Routing Strategy
**Question**: How to map incoming Telegram message → tenant?

| Option | Merits | Demerits |
|--------|--------|----------|
| **A. Channel.external_id == str(chat_id)** | ✅ Exact routing per known conversation<br>✅ Zero ambiguity - each chat maps to one tenant<br>✅ Supports per-tenant branding (different bots)<br>✅ Matches existing WhatsApp pattern (Channel.external_id = phone number)<br>✅ Enables multi-tenant isolation by default | ❌ Requires creating Channel row for each new chat<br>❌ Cannot route first-time messages without fallback<br>❌ Channel table grows with number of conversations |
| **B. Channel.external_id stores bot username** | ✅ Single Channel row per bot<br>✅ Fixed routing target<br>✅ Simple to implement | ❌ Requires `to` field from Telegram (not available in Bot API updates)<br>❌ Cannot distinguish which tenant the user intended<br>❌ All messages go to same tenant unless complex logic |
| **C. Single bot per tenant** (Selected) | ✅ Natural isolation<br>✅ Each venue has branded bot (@venueconcierge)<br>✅ Channel row maps bot username → tenant<br>✅ No routing ambiguity<br>✅ Easy to identify tenant from bot token<br>✅ Clear separation of concerns<br>✅ Simpler mental model: one bot per venue<br>✅ Matches user's explicit selection | ❌ Requires managing multiple bot tokens<br>❌ Each venue needs own @BotFather setup<br>❌ Higher operational overhead<br>❌ More complex initial setup for venues |
| **D. Shared bot + TELEGRAM_DEFAULT_TENANT fallback** | ✅ Works with single shared bot for pilot<br>✅ First-time messages route to default tenant<br>✅ Known conversations use Channel.external_id lookup<br>✅ Matches WhatsApp sandbox pattern exactly<br>✅ Low operational overhead for pilot | ❌ Requires fallback logic<br>❌ First-time messages may go to wrong tenant<br>❌ Requires cleanup/migration when scaling to per-tenant bots |

**Recommendation**: **Single bot per tenant** — selected per user request for clear tenant isolation and simpler operational model.

**Rationale**:
- User explicitly selected single bot per tenant for clearer tenant isolation
- Each venue gets its own branded bot (@venueconcierge or similar)
- Channel row maps bot username (in external_id) → tenant for direct lookup
- No routing ambiguity or fallback logic needed
- Simpler mental model: one bot, one venue, one set of credentials
- Aligns with production architecture from the start

### D5: Media Handling
**Question**: Support images/documents/voice from guests?

| Option | Merits | Demerits |
|--------|--------|----------|
| **Phase 1: Text only** (Recommended for MVP) | ✅ Fastest path to market<br>✅ Covers 90%+ of booking enquiries<br>✅ Reuses existing text-only orchestrator/tools<br>✅ No additional complexity in pipeline<br>✅ Simple to test and validate<br>✅ Minimal security surface area | ❌ Cannot process images (menu photos, dietary docs)<br>❌ Cannot process documents (PDF menus, ID verification)<br>❌ Voice messages require separate STT effort |
| **Phase 2: Images/Docs** | ✅ Enables menu photo sharing<br>✅ Allows document verification (ID, certificates)<br>✅ Uses existing Bot API `getFile` → download<br>✅ Can feed into RAG for visual QA (future)<br>✅ Leverages existing file handling patterns | ❌ Requires storage (local/S3) for downloaded files<br>❌ Virus/malware scanning considerations<br>❌ Content moderation needed<br>❌ Increases attack surface |
| **Voice: Defer** | ✅ Voice-to-text is separate complex effort<br>✅ Requires STT service (Whisper, etc.)<br>✅ Significantly increases latency/cost<br>✅ Privacy considerations for voice storage<br>✅ Not core to booking flow | ❌ Guests may prefer voice input<br>❌ Accessibility consideration<br>❌ Competitors may offer voice |

**Recommendation**: **Phase 1: Text only. Phase 2: Images/Docs. Voice: defer.**

**Rationale**:
- Text covers 90%+ of booking enquiries
- Images: menu photos, dietary restriction screenshots — useful but not MVP
- Voice: requires STT pipeline (Whisper) — separate effort
- Bot API `getFile` → download → process → RAG/guardrails

### D6: 24-Hour Window Difference
**Question**: Telegram has no 24h free-form window like WhatsApp. How to handle?

| Option | Merits | Demerits |
|--------|--------|----------|
| **No template restriction needed** (Recommended) | ✅ Simpler implementation<br>✅ Always free-form messaging<br>✅ Matches Telegram Bot API capabilities<br>✅ Removes template approval workflow complexity<br>✅ Consistent behavior 24/7<br>✅ Easier to explain to venues | ❌ Cannot leverage high-deliverability template messages<br>❌ May have slightly lower delivery guarantees<br>❌ Inconsistent with WhatsApp behavior (venues used to templates) |
| **Simulate 24h window** | ✅ Matches WhatsApp UX for venues<br>✅ Allows template use outside window<br>✅ Familiar behavior for existing WhatsApp users | ❌ Significant complexity increase<br>❌ Requires tracking last message timestamp<br>❌ Template management system needed<br>❌ Error handling for template rejections<br>❌ Goes against Telegram's natural flow |
| **Always use templates** | ✅ Highest deliverability guarantees<br>✅ Consistent with WhatsApp template model<br>✅ Pre-approved content reduces risk | ❌ Severely restricts conversation flow<br>❌ Requires template for every possible response<br>❌ Impossible for dynamic content (prices, availability)<br>❌ Poor user experience |

**Recommendation**: **No template restriction needed** — always free-form. Simplify `build_telegram_client` vs WhatsApp's `send_template`.

**Rationale**:
- Telegram Bot API: always sendMessage, no template approval flow
- Remove complexity from client; webhook handler stays simple
- Document difference in config comments

### D7: Authentication / Webhook Verification
**Question**: How to verify inbound webhook is from Telegram?

| Option | Merits | Demerits |
|--------|--------|----------|
| **Secret token in header** (Recommended) | ✅ Telegram-recommended method<br>✅ Set via `setWebhook?secret_token=<random>`<br>✅ Header validation: `X-Telegram-Bot-Api-Secret-Token`<br>✅ Matches Twilio signature pattern (1 line in router)<br>✅ No URL manipulation required<br>✅ Works with any webhook framework<br>✅ Easy to rotate/update | ❌ Requires storing secret in config<br>❌ Must remember to set during webhook registration<br>❌ Another secret to manage |
| **Query param validation** | ✅ Simple to implement<br>✅ No header parsing needed<br>✅ Token in URL: `?token=<secret>` | ❌ Secrets in logs/proxies (less secure)<br>❌ URL length limits<br>❌ Less standard<br>❌ Telegram docs recommend header method |
| **IP address allowlist** | ✅ No secrets needed<br>✅ Only accept from Telegram IP ranges | ❌ Telegram IP ranges change infrequently but do change<br>❌ Requires periodic updates<br>❌ Less secure if IP spoofed<br>❌ Doesn't protect against compromised Telegram servers |
| **No validation (dev only)** | ✅ Simplest possible<br>✅ No configuration needed | ❌ Anyone can send fake updates<br>❌ Security vulnerability<br>❌ Not acceptable for production |

**Recommendation**: **Secret token in header** (`X-Telegram-Bot-Api-Secret-Token`)

**Rationale**:
- Set via `setWebhook?secret_token=<random>`
- Header validation = 1 line in router, matches Twilio signature pattern
- Store in `TELEGRAM_WEBHOOK_SECRET` env var

### D8: Callback Queries (Inline Buttons)
**Question**: Support approval buttons in Telegram (like WhatsApp interactive)?

| Option | Merits | Demerits |
|--------|--------|----------|
| **Defer to Phase 2** (Recommended) | ✅ Faster MVP delivery<br>✅ Text commands work for approvals ("APPROVE #123")<br>✅ Staff console already has web UI for approvals<br>✅ Simpler router (only handle message updates)<br>✅ Less complexity to test/validate<br>✅ Aligns with "text-first" phase 0 product | ❌ Less polished UX than buttons<br>❌ Requires guests to remember command format<br>❌ More prone to user error (typos)<br>❌ Not as discoverable as buttons |
| **Implement callback queries** | ✅ Rich interactive experience<br>✅ Inline "Approve/Reject" buttons<br>✅ Discoverable and error-proof<br>✅ Matches WhatsApp interactive capabilities<br>✅ Modern chat UX expectation | ❌ Significantly more complex router<br>❌ Must handle `callback_query` update type<br>❌ Requires tracking message IDs for button context<br>❌ Increases state complexity<br>❌ More edge cases to handle (expired queries, etc.)<br>❌ Slows down MVP delivery |
| **Hybrid: text commands + basic buttons** | �Buttom | Guests get choice of interaction method<br>✅ Buttons for common actions (yes/no)<br>✅ Text for complex responses | ❌ Worst of both worlds<br>❌ Increases complexity significantly<br>❌ Inconsistent UX<br>❌ More code paths to maintain |

**Recommendation**: **Defer to Phase 2** — text commands work for MVP ("APPROVE #123", "CANCEL #123")

**Rationale**:
- WhatsApp uses interactive buttons for approvals; Telegram can use text commands initially
- Callback queries add router complexity (different update type)
- Staff console already has web UI for approvals — Telegram is guest-facing

### D9: Group/Channel Support
**Question**: Allow concierge in Telegram groups?

| Option | Merits | Demerits |
|--------|--------|----------|
| **Explicitly disable for MVP** (Recommended) | ✅ Simpler implementation<br>✅ Privacy: no guest data exposed in groups<br>✅ Clear thread ownership (1:1 conversations)<br>✅ Matches venue use case: private booking chats<br>✅ Reduces security considerations<br>✅ Easier to test and validate | ❌ Cannot assist groups planning events<br>❌ Venue staff cannot use group chats with bot<br>❌ Requires guests to start private chat |
| **Allow groups with restrictions** | ✅ Enable group event planning<br>✅ Venue staff can communicate via group<br>✅ More flexible usage patterns<br>✅ Matches how groups actually use Telegram | ❌ Privacy concerns: guest data visible to all group members<br>❌ Thread ambiguity: which user is the guest?<br>❌ Complex permission/model needed<br>❌ Moderation challenges (spam, abuse)<br>❌ Significant increase in complexity |
| **Full group support** | ✅ Maximum flexibility<br>✅ Works in any Telegram context<br>✅ Future-proof | ❌ Highest complexity<br>❌ Major privacy and security considerations<br>❌ Complex threading and user identification<br>❌ Significant moderation overhead<br>❌ Not aligned with primary use case |

**Recommendation**: **Explicitly disable for MVP** — only private chats

**Rationale**:
- Privacy: guest data in groups
- Thread ambiguity: which user is the guest?
- Venue use case: 1:1 booking conversations
- Add `chat.type == "private"` guard in adapter

---

## Implementation Plan

### Files to Create

```
concierge/app/channels/telegram/
├── __init__.py              # exports
├── adapter.py               # TelegramAdapter + TelegramInbound
├── client.py                # TelegramClient + NullTelegramClient + build_telegram_client
└── router.py                # inbound webhook + health + set_webhook helper
```

### Files to Modify

| File | Change |
|------|--------|
| `app/models/enums.py` | Add `telegram = "telegram"` to `ChannelType` |
| `app/config.py` | Add `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_WEBHOOK_URL`, `TELEGRAM_DEFAULT_TENANT` |
| `app/main.py` | Import & include `telegram.router` |
| `app/routers/__init__.py` | Export telegram router (optional) |

---

### Task List

#### Phase 1: Core Channel (MVP — Text Only)

- [ ] **T1** Add `telegram` to `ChannelType` enum
- [ ] **T2** Create `app/channels/telegram/adapter.py`
  - `TelegramInbound` dataclass with `from_update()` handling `message` + `edited_message` + MTProto update types
  - `TelegramAdapter.to_inbound()` → `InboundMessage` with `conversation_ref=str(chat_id)`
  - Guard: reject non-private chats (`update.message.chat.type != "private"`)
- [ ] **T3** Create `app/channels/telegram/client.py`
  - `TelegramMTProtoClient` using Telethon or similar library
  - Handle MTProto connection, session management, updates
  - Implement `send_text(chat_id, text)` via MTProto messages.SendMessage
  - `NullTelegramClient` for dev
  - `build_telegram_client()` reads MTProto credentials (`TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, etc.)
- [ ] **T4** Create `app/channels/telegram/router.py`
  - `GET /webhooks/telegram` → health check
  - `POST /webhooks/telegram` → verify secret token → parse → `handle_inbound` → reply
  - Helper: `POST /webhooks/telegram/set` to call `setWebhook` (dev convenience)
  - Note: For MTProto, we still need webhook for incoming updates, but outbound uses MTProto connection
- [ ] **T5** Add MTProto config fields to `app/config.py`
- [ ] **T6** Register router in `app/main.py`
- [ ] **T7** Create migration for `ChannelType` enum (VARCHAR + CHECK → just add value)
- [ ] **T8** Write unit tests: adapter, client, router happy paths

#### Phase 2: Media & Rich Features

- [ ] **T9** Extend adapter: parse `photo`, `document`, `location`, `contact` from MTProto updates
- [ ] **T10** Extend client: `send_photo`, `send_document`, `send_location` via MTProto
- [ ] **T11** Media download via MTProto `getFile` → store in object storage / local → RAG ingestion

#### Phase 3: Operational Hardening

- [ ] **T12** Deduplication: Redis `tg:seen:{update_id}` (like WhatsApp `wa:seen:{sid}`)
- [ ] **T13** Retry logic: `send_with_retry` wrapper (reuse WhatsApp pattern)
- [ ] **T14** Rate limiting awareness (MTProto has different limits than Bot API)
- [ ] **T15** Webhook secret rotation endpoint
- [ ] **T16** Session management: handle MTProto session expiration/refresh

#### Phase 4: Multi-Tenant Polish

- [ ] **T17** Per-tenant bot support (separate MTProto sessions per tenant in `Tenant.config`)
- [ ] **T18** Staff approval via callback queries (inline "Approve/Reject" buttons) via MTProto

---

## Data Flow (MVP)

```
Guest → Telegram → MTProto Server (updates)
          ↓
Webhook Server (configured via setWebhook) 
          ↓
POST /webhooks/telegram (FastAPI)
          ↓
validate X-Telegram-Bot-Api-Secret-Token
          ↓
TelegramInbound.from_update(update)
          ↓
TelegramAdapter.to_inbound(tenant_slug) → InboundMessage
          ↓
base.handle_inbound() → orchestrator → tools → RAG → reply chunks
          ↓
TelegramMTProtoClient.send_text(chat_id, reply)  // Via MTProto connection
          ↓
Guest receives message
```

---

## Failure Modes & Mitigations

| Failure | Detection | Mitigation |
|---------|-----------|------------|
| Webhook URL unreachable | Health check fails | `setWebhook` helper in router; alert on 5xx |
| Invalid secret token | 403 in logs | Rotate via `/set` endpoint; log attempts |
| MTProto session expired | Auth errors, update failures | Session refresh/re-authentication logic |
| MTProto connection dropped | No updates received | Reconnect with exponential backoff |
| API ID/Hash invalid | Auth failure during connection | Validate credentials on startup |
| Rate limited (flood wait) | Specific MTProto error codes | Respect flood wait times; queue messages |
| Group message received | `chat.type != "private"` | Reject early in adapter; log |
| Duplicate update | Redis `tg:seen:{update_id}` exists | Skip processing; return 200 |
| Long message (>4096 chars) | MTProto error | Chunk in client; send multiple messages |
| Session file corruption | Client fails to start | Backup session; allow re-authentication |

---

## Validation Plan

### Unit Tests
- `test_adapter.py`: `from_update` parses text, edited, rejects group/channel
- `test_client.py`: `TelegramMTProtoClient` connection, session handling, message sending
- `test_router.py`: webhook validates secret, routes to tenant, calls orchestrator

### Integration Tests
- `docker compose up` with test MTProto credentials → send message → verify reply
- Multi-tenant: two Channel rows, different bot usernames, verify isolation
- Session persistence: restart service, verify session restored

### Manual Verification
1. Create bot via `@BotFather` and get API ID/Hash from my.telegram.org
2. Set webhook: `curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://dev.domain/webhooks/telegram&secret_token=<SECRET>"`
   - Note: For MTProto, we still need a bot token for webhook setup
3. Initialize MTProto session (may require QR code or SMS code)
4. Message bot → verify concierge replies
5. Check conversation in staff console (`/conversations`)

---

## Rollout Strategy

1. **Local Dev**: 
   - Set up MTProto session (may require manual QR code/SMS authentication initially)
   - `TELEGRAM_WEBHOOK_URL=""` triggers polling mechanism for updates (adapted for MTProto)
   - Session string stored locally for development

2. **Staging**: 
   - Pre-authorized MTProto session string stored securely
   - Shared webhook endpoint with `TELEGRAM_DEFAULT_TENANT` fallback (if needed during transition)
   - Each tenant has their own API ID/Hash but shares webhook domain

3. **Production Pilot**: 
   - One MTProto session per venue (separate API ID/Hash from my.telegram.org)
   - Each venue has branded bot (@venueconcierge) with dedicated session
   - Webhook per tenant or shared with tenant identification via request headers/path

4. **Future**: 
   - Group support, callback queries, media
   - Session pooling and optimization

---

## Open Questions

### D10: Bot Token Management (API ID/Hash for MTProto)
**Question**: Should `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` be per-tenant in `Tenant.config` from Day 1, or can they be shared?

| Option | Merits | Demerits |
|--------|--------|----------|
| **Shared API ID/Hash** (Recommended for simplicity) | ✅ Simpler setup<br>✅ One pair to manage from my.telegram.org<br>✅ Lower operational overhead<br>✅ Easy to rotate/update<br>✅ Works if all tenants use same app registration | ❌ Less security isolation<br>❌ Compromise affects all tenants<br>❌ All tenants appear as same "app" to Telegram<br>❌ May hit rate limits faster if shared |
| **Per-tenant API ID/Hash** | ✅ Better security isolation<br>✅ Each tenant has independent app registration<br>✅ Independent rotation per tenant<br>✅ Tenants appear as separate apps to Telegram<br>✅ Matches per-tenant bot model | ❌ More pairs to manage<br>❌ Each tenant needs own my.telegram.org registration<br>❌ Higher operational overhead<br>❌ More complex initial setup |

**Lean**: Start with shared API ID/Hash for pilot; move to per-tenant when security isolation is required

### D11: Phone Number Management
**Question**: How to handle the phone number required for MTProto authentication?

| Option | Merits | Demerits |
|--------|--------|----------|
| **Shared phone number** (Not recommended) | ✅ Simpler setup<br>✅ One number to manage | ❌ Major security risk<br>❌ All sessions tied to one number<br>❌ Cannot have concurrent sessions<br>❌ Violates Telegram ToS |
| **Per-tenant phone number** (Required) | ✅ Each tenant has independent identity<br>✅ No session conflicts<br>✅ Proper isolation<br>✅ Matches Telegram's phone-based auth model | ❌ Requires managing multiple phone numbers<br>❌ Each tenant needs access to receive SMS/calls<br>❌ Higher operational overhead<br>❌ May require virtual phone numbers/services |

**Lean**: Per-tenant phone number required; each tenant must provide a number capable of receiving Telegram authentication codes

### D12: Session Storage Strategy
**Question**: How to store MTProto session strings securely?

| Option | Merits | Demerits |
|--------|--------|----------|
| **Encrypted in Tenant.config** (Recommended) | ✅ Simple implementation<br>✅ Backed by existing tenant config system<br>✅ Can leverage existing encryption<br>✅ Easy to backup/restore<br>✅ Access controlled via tenant permissions | ❌ Requires encryption key management<br>❌ If config is compromised, sessions are exposed<br>❌ May need rotation strategy |
| **Separate session store** (e.g., Redis, filesystem) | ✅ Decoupled from main DB<br>✅ Can optimize for session-specific access patterns<br>✅ Easier to rotate/separate credentials<br>✅ Can use specialized session storage | ❌ More complex to implement<br>❌ Additional system to manage<br>❌ Requires synchronization with tenant lifecycle<br>❌ More failure points |
| **Client-side session** (Not feasible) | ✅ No server-side storage needed | ❌ Not possible for server-based concierge<br>❌ Requires client to maintain session<br>❌ Doesn't work for 24/7 service |

**Lean**: Encrypted session strings stored in `Tenant.config` using existing encryption infrastructure

---

### D6-D9: Using Recommended Options

As indicated, for decisions D6 through D9, we will proceed with the previously recommended options:

- **D6: 24-Hour Window Difference** → No template restriction needed (always free-form)
- **D7: Authentication / Webhook Verification** → Secret token in header (`X-Telegram-Bot-Api-Secret-Token`)
- **D8: Callback Queries (Inline Buttons)** → Defer to Phase 2 (text commands for MVP)
- **D9: Group/Channel Support** → Explicitly disable for MVP (only private chats)

---

## Out of Scope (Explicit)

- Voice message transcription (requires STT service)
- Inline mode / `@bot` queries in other chats
- Telegram Stars / payments
- Bot API 7.0+ features (business messages, reactions) — evaluate later

---

## Dependencies

- **New runtime deps**: `telethon` (for MTProto) - add to `pyproject.toml`
- **Existing deps**: `httpx` already in `pyproject.toml` (for webhook validation)
- **Database migration**: Add `telegram` to `ChannelType` CHECK constraint (light, VARCHAR-backed)
- **Config**: 5 new env vars for MTProto (`TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE_NUMBER`, `TELEGRAM_SESSION_STRING`, `TELEGRAM_WEBHOOK_SECRET`)

---

## Next Steps

1. ✅ Design decisions confirmed: D1=MTProto, D2=Webhook(+local polling), D3=chat_id, D4=Single bot per tenant, D5=MVP text only
2. Write the finalized plan to `.kilo/plans/1788173977314-telegram-channel-integration.md`
3. Implementation agent executes T1–T8 (Phase 1: Core Channel)