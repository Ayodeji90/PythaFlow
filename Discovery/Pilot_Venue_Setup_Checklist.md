# Pilot Venue Setup Checklist — Balance Concierge

Internal runbook for taking a venue live on the concierge. One pass per venue.
Companion to the customer-facing `Pilot_Offer_OnePager.md`.

> **Assumes** the stack is deployed and healthy (`GET /health` → `db:true, redis:true`)
> and you have shell access to run the seed script or SQL. Telegram specifics are
> in §7 — the per-venue steps there are the same for every venue.

---

## 1. Collect venue facts (before you start)

| Fact | Example | Used for |
|------|---------|----------|
| Venue name | Demo Bistro | Tenant row, email display name |
| Slug (unique, URL-safe) | `demo` | Webhook paths, API calls |
| Timezone (IANA) | `America/Nassau` | Booking times, hours logic |
| Languages | `["en"]` | Guest-facing replies |
| Brand voice summary | "Warm, concise — like a great maître d'" | `brand_voice` fallback |
| Structured voice config | tone / do / don't / length-by-channel | `voice_config` JSONB (see §4) |
| Menu, hours, policies, FAQ text | copy or file | Knowledge base (§5) |
| Staff console tokens | one per staff member | `Tenant.config["staff_tokens"]` |

## 2. Create the tenant + channels

There is no tenant-creation API yet — create the row via the seed script or SQL.

```bash
cd concierge
uv run python scripts/seed.py     # creates tenant slug='demo' + owner + webchat + email
```

For a new venue, edit/extend `scripts/seed.py` (copy the tenant block) with the
venue's slug, name, timezone, and `voice_config`, then run it. The seed is
idempotent — safe to re-run.

Verify: tenant row exists; webchat + email `Channel` rows exist for it.

## 3. Set staff console access

Staff authenticate with an `X-Staff-Token` header. Store a token list per venue:

```sql
UPDATE tenants
SET config = config || '{"staff_tokens": ["<random-token-1>", "<random-token-2>"]}'
WHERE slug = '<venue-slug>';
```

Verify: `GET /api/conversations` with the header returns the venue's own list
(and an empty list before any guest messages).

## 4. Configure brand voice

Two layers, both read by the orchestrator:

1. **`voice_config` (structured, preferred)** — JSONB on the tenant:
```json
{
  "tone": "casual",
  "do": ["Use emoji", "Be warm and friendly"],
  "dont": ["Use corporate language"],
  "length_by_channel": {"whatsapp": "2 sentences", "webchat": "3 sentences"},
  "greeting": "Hey there! Welcome to Demo Bistro!",
  "post_draft_message": "Done! Your {type} is being reviewed by the {name} team."
}
```
2. **`brand_voice` (free-text fallback)** — used when `voice_config` is empty.

Verify: a test chat reply matches the tone and channel length.

## 5. Ingest the knowledge base

Chunk + embed each source doc (menu, hours, policies, FAQ) per venue:

```bash
curl -X POST <api>/api/kb -H 'content-type: application/json' -d '{
  "tenant": "<venue-slug>",
  "source": "menu",                       # stable id — re-POST replaces it
  "title": "Demo Bistro menu",
  "text": "<full doc text>"
}'
```

Verify: response returns `chunks > 0`; ask the concierge a question whose answer
is only in the KB and confirm it answers from it (no invention), and that a
non-KB question yields "I'll check with the team".

## 6. Channels — WhatsApp, WebChat, Email

| Channel | Setup | Verify |
|---------|-------|--------|
| WebChat | Works out of the box once the tenant exists. Dev page at `/dev/chat` (dev only). | Send a message → reply in the venue's voice |
| WhatsApp (Twilio sandbox) | Console.twilio.com → Messaging → WhatsApp Sandbox. Join the sandbox with the venue's phone, point "When a message comes in" at `https://<your-public-url>/webhooks/whatsapp`. Set `WHATSAPP_DEFAULT_TENANT=<slug>` in env. | Guest message → reply; wrong-number "To" still lands on the venue via the default tenant |
| Email | Channel row with `external_id` = the venue's inbound address; SMTP creds in env; inbound parse at `/api/email/inbound`. | Send an enquiry email → concierge replies from the venue's address |

---

## 7. Telegram (per-venue) — the full setup

Telegram is **Bot API only, one bot per venue**. A bot token from @BotFather is
the only credential — no phone number, no MTProto session. The guest messages
`@VenueBot` and the concierge replies from the **same bot** (the venue's token
is stored on its Telegram `Channel` row). Design doc:
`.kilo/plans/1788173977314-telegram-channel-integration.md`.

### 7.1 Create the bot (venue owner, ~2 minutes, or you on their behalf)
1. In Telegram, message **@BotFather** → `/newbot`.
2. Name it after the venue, username e.g. `DemoBistroBot`.
3. Copy the token (`123456:ABC-...`). Treat it as a secret — it authorizes
   sending as the venue's bot.
4. Optional: set a bot photo/description in BotFather for brand polish.

### 7.2 Store the token on the venue's Channel row
The seed provisions the channel when these env vars are present at seed time:

```bash
TELEGRAM_BOT_TOKEN=123456:ABC-... \
TELEGRAM_BOT_USERNAME=DemoBistroBot \
TELEGRAM_WEBHOOK_SECRET=<random-secret> \
uv run python scripts/seed.py
```

This writes `Channel(external_id='DemoBistroBot', config={"bot_token": …,
"webhook_secret": …})` for the venue. On an existing deployment without seed
access, add the row with SQL instead (type `telegram`, `active=true`).

> **Secret hygiene:** give **each venue its own `webhook_secret`** (random ≥ 16
> chars) in `Channel.config`. The global `TELEGRAM_WEBHOOK_SECRET` env var is
> only a fallback for venues without one.

### 7.3 Register the webhook
Each bot must point at the venue's per-tenant webhook path. The API is public,
so use a tunnel in dev or the real domain in prod:

```bash
curl -X POST <api>/webhooks/telegram/set -H 'content-type: application/json' -d '{
  "tenant_slug": "<venue-slug>",
  "url": "https://<your-public-url>"        # /webhooks/telegram/<slug> is appended
}'
```

This calls Telegram's `setWebhook` with the secret token and stores the bot
@username on the channel. Wrong token / missing channel → 400; unknown slug → 404.

Verify: re-run `POST /webhooks/telegram/delete` then `/set` cleanly (idempotent),
and confirm the stored `Channel.external_id` is the bot's @username.

### 7.4 End-to-end test (per venue)
1. From a **separate Telegram account**, open a chat with the venue's bot.
2. Send a booking enquiry (e.g. "table for 2 tomorrow at 7pm").
3. Expected: the concierge replies **from the same bot** in the venue's voice,
   drafts a booking → staff approve in the console → confirmation is sent.
4. Check the conversation appears under the venue in `GET /api/conversations`
   and the live stream (`GET /api/conversations/{id}/events`).

### 7.5 Negative tests (do these before launch)
| Test | Expected |
|------|----------|
| Wrong `X-Telegram-Bot-Api-Secret-Token` | HTTP 403 (logged) |
| Group chat message to the bot | Acknowledged + ignored (private chats only) |
| Duplicate update (Telegram retry) | Skipped via Redis dedup, no double reply |
| Long reply (>4096 chars) | Split into multiple messages |
| Venue's token removed from `Channel.config` | Dev: reply logged, not sent; prod: loud error |

### 7.6 Removing / rotating a venue's bot
- **Remove:** `curl -X POST <api>/webhooks/telegram/delete -d '{"tenant_slug": "<slug>"}'`
- **Rotate token:** new token from @BotFather → update `Channel.config.bot_token`
  → re-run `/set` (§7.3). Old token dies instantly on Telegram's side.
- **Rotate secret:** new `webhook_secret` in `Channel.config` → re-run `/set`.

---

## 8. Go-live smoke test (after all channels configured)

1. `GET /health` → all green.
2. WebChat question → grounded, in-voice reply; booking draft flows to approvals.
3. WhatsApp enquiry from a real phone → reply within seconds; wrong "To" falls to
   default tenant.
4. Telegram enquiry from a real account → reply from the venue's bot (§7.4).
5. Approve a draft in the console → guest gets the confirmation on the original
   channel.
6. `GET /api/conversations` shows every channel's threads under the one venue;
   SSE stream updates live.
7. Reminder fires for a booked reservation (scheduler task running).

## 9. Handover to the venue

- 15-minute walkthrough: what the concierge answers, what it escalates, how
  staff approve bookings and read conversations, the weekly report promise.
- Leave them the venue's `X-Staff-Token` for the console.
- Note: guest-facing phone/WhatsApp/Telegram channels work 24/7; staff approvals
  can happen from a phone browser.
