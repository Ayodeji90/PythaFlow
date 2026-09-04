# Balance Concierge

The AI concierge for hospitality — Phase 0 (text-first). See the plans in
`../Discovery/`: system architecture, the 30-day sprint, and the Week-1 build spec.

## Run locally (Day 1)

```bash
cd concierge
cp .env.example .env          # then add your NVIDIA key: LLM_API_KEY=nvapi-...
docker compose up --build     # api + Postgres(pgvector) + Redis
curl -s localhost:8000/health # -> {"status":"ok","db":true,"redis":true,...}
```

Or run the app on the host against just the datastores:

```bash
uv sync
docker compose up -d db redis
uv run uvicorn app.main:app --reload
```

LLM smoke test (exercises the whole provider seam):

```bash
uv run python scripts/check_llm.py
```

## Architecture — the LLM seam

The app core depends only on a stable **LLMService**. It never imports a vendor
SDK. Swapping providers = editing `.env`; adding a non-OpenAI vendor = one new
wrapper file.

```
app core (routers, orchestrator…)     ← stable
      │  depends only on ↓
LLMService  (app/llm/service.py)       ← stable interface: generate(msgs, tier)
      │  delegates to ↓
Provider wrapper (app/llm/providers/*) ← swappable, one per vendor shape
      │  calls ↓
Vendor API (NVIDIA NIM / OpenAI / Groq / Mistral / local …)
```

## Channels

Guests reach the concierge through channel adapters (`app/channels/`); each
channel owns an adapter (`to_inbound()`), an outbound client, and a router, and
everything funnels into the same `handle_inbound()` pipeline.

| Channel | Router | Thread key | Outbound |
|---------|--------|------------|----------|
| WebChat | `routers/webchat.py` (WebSocket + REST) | browser session | JSON over the wire |
| WhatsApp | `routers/whatsapp.py` | `WaId` (phone) | Twilio REST |
| Email | inbound parse + SMTP reply | `Message-ID` thread | SMTP |
| **Telegram** | `channels/telegram/router.py` | `chat_id` | **Bot API** (`sendMessage`) |

### Telegram (Bot API)

Telegram is **Bot API only** — one bot per venue, created in ~2 minutes via
[@BotFather](https://t.me/BotFather). No MTProto/Telethon, no phone number, no
session: the bot token is the only credential, and the bot the guest messages is
the bot that replies (one identity end-to-end). Design decisions live in
`.kilo/plans/1788173977314-telegram-channel-integration.md`.

Per-venue credentials are stored on the tenant's Telegram `Channel` row:
`config.bot_token`, `config.webhook_secret`, and the bot @username on
`external_id`. Two optional env vars exist: `TELEGRAM_WEBHOOK_SECRET` (fallback
secret) and `TELEGRAM_DEFAULT_TENANT` (slug for the shared sandbox path).

Webhook endpoints (per-tenant path is the multi-tenant one; `/set` registers it):

```
GET  /webhooks/telegram                health check
POST /webhooks/telegram                sandbox → TELEGRAM_DEFAULT_TENANT
POST /webhooks/telegram/set            {tenant_slug, url} → setWebhook + store @username
POST /webhooks/telegram/delete         {tenant_slug} → deleteWebhook
POST /webhooks/telegram/{tenant_slug}  inbound (secret-token header required)
```

Try it locally:

```bash
# 1. create a bot with @BotFather and export its token
TELEGRAM_BOT_TOKEN=123456:ABC... uv run python scripts/seed.py

# 2. expose the API (ngrok/cloudflared) and register the webhook
curl -X POST localhost:8000/webhooks/telegram/set \
  -H 'content-type: application/json' \
  -d '{"tenant_slug": "demo", "url": "https://<your-tunnel-url>"}'

# 3. message your bot — the concierge replies from the same bot
```

## Layout

```
app/
  main.py            FastAPI app factory + lifespan (pings db/redis)
  config.py          Settings (env-driven)
  db.py              async SQLAlchemy engine + ping
  deps.py            FastAPI dependencies
  services/redis.py  Redis client + ping
  routers/health.py  GET /health
  llm/
    base.py          LLMProvider ABC + message/result types
    service.py       LLMService — the stable app-facing interface
    factory.py       build_llm_service() — picks the provider from Settings
    providers/
      openai_compatible.py   NVIDIA NIM / OpenAI / Groq / Mistral / Ollama …
scripts/check_llm.py LLM smoke test
init/                Postgres init (CREATE EXTENSION vector)
```
