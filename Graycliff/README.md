# Graycliff AI Platform — PythaFlow Demo

Five AI solutions for Graycliff Hotel & Restaurant (Nassau), built as one
integrated demo: Smart Menu & Dynamic Pricing, Guest Personalization,
Voice Ordering & Reservations, AI Marketing Content, and a Contactless
QR-Menu with AI Upsell.

Runs entirely on a realistic **synthetic dataset** (12 months of seasonal
Nassau fine-dining POS history) until the client shares real data.

## Quick start (local dev) — one command

```bash
./dev.sh
```

Starts everything with hot-reload; Ctrl+C stops it all. Endpoints:

| URL | What |
|---|---|
| `http://localhost:8000/site` | graycliff.com mockup with the embedded concierge widget |
| `http://localhost:5173` | guest menu · `/dashboard` · `/knowledge` · `/voice` · `/marketing` |
| `http://localhost:8000/docs` | API reference |

First run only: `cd frontend && npm install`, and regenerate seed data if
needed with `../.venv/bin/python data/generate_graycliff_data.py`.

First backend boot seeds `backend/graycliff.db` (SQLite) from `data/seed/`.
Delete that file to reset the demo to a clean state.

### Docker

```bash
docker compose up --build
# frontend: http://localhost:5173   backend: http://localhost:8000
```

### Environment (optional)

Set in the repo-root `.env` (see `.env.example`):

| Variable | Effect |
|---|---|
| `LLM_PROVIDER` | `auto` (default) \| `anthropic` \| `openai` \| `none` |
| `ANTHROPIC_API_KEY` | Enables the Claude provider |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | Enables any OpenAI-compatible provider (OpenAI, Groq, Mistral, local Ollama) |
| `LLM_MODEL_FAST` / `LLM_MODEL_QUALITY` | Optional model overrides per tier (fast = voice turns, quality = marketing copy) |

Without any provider, voice and marketing fall back to rule-based/template
logic — the demo still runs, clearly labelled in the UI.

## The pages

| URL | Audience | What it shows |
|---|---|---|
| `/?table=12` | Guest | QR menu with cart and AI upsell |
| `/?table=12&guest=7` | Returning guest | Adds the personalized "For you" section |
| `/dashboard` | Manager | Forecast, dynamic-pricing approvals, waste risk, sales |
| `/voice` | Guest | Voice/text concierge — orders & reservations |
| `/marketing` | Marketing | AI copy studio with approval workflow |
| `:8000/api/qr/12` | Ops | Printable QR PNG for table card 12 |

## The 10-minute pitch script

1. **Open `/?table=12&guest=7`** (phone-sized window). Point out the
   personalized "For you" picks with reasons. Add the **Lobster Thermidor**
   — the sommelier-pairing prompt appears. Accept it. Review order → note
   the upsell suggestions under "May we also suggest" → **Send to kitchen**.
   *Message: every table upsells itself, politely.*
2. **Open `/dashboard`.** Tonight's revenue includes the order just placed.
   Walk the stat row: **waste at risk** is real money ($3k+/week). Show the
   covers forecast picking up Saturday and festival peaks.
3. **Scroll to Dynamic pricing.** Read one scarcity rationale aloud (the
   lobster one) and one waste rationale (the foie gras). Click **Apply** on
   one — the guest menu price updates live. *Message: AI suggests, the
   manager decides; guardrails are visible.*
4. **Open `/voice`.** Click the sample phrase "Book a table for four
   tomorrow at 8pm" — reservation confirmed and spoken back. Then order by
   voice/text: "the wagyu and a glass of Barolo".
5. **Open `/marketing`.** Generate an Instagram post — it references this
   week's actual best seller and the next event. Approve → Schedule.
   *Message: on-brand content in seconds, human always approves.*
6. **Close on `/dashboard`** — the reservation and orders from steps 1–4
   are all visible. One platform, five modules, live loop.

## Architecture (demo build)

```
frontend/  React + Vite SPA, dark luxury theme, recharts
backend/   FastAPI + SQLite (SQLAlchemy)
  app/services/forecast.py     trailing level × weekday profile × event uplift
  app/services/pricing.py      rule engine + guardrails (≥2× cost, ±15% cap)
  app/services/recommender.py  co-occurrence CF + content tags + guest history
  app/services/llm.py          voice/marketing AI logic (vendor-blind)
  app/services/llm_service.py  LLMService interface + provider factory
  app/services/providers/      one wrapper per vendor (anthropic, openai-compatible)
data/      synthetic dataset generator + seed CSVs
```

### AI provider isolation

The app core never touches a vendor SDK — it talks to a stable interface,
and each provider is a thin replaceable wrapper:

```
App Core (routers, llm.py prompts & fallbacks)   ← stable
        ↓
LLMService interface (llm_service.py)            ← stable: generate(prompt, tier)
        ↓
Provider wrapper (services/providers/*)          ← swap freely
        ↓
Vendor API (Anthropic / OpenAI / Groq / Ollama…)
```

Switching vendors or models = edit `.env` (`LLM_PROVIDER`,
`LLM_MODEL_FAST`, `LLM_MODEL_QUALITY`) and restart. Adding a vendor =
one new file in `services/providers/` implementing `generate()`; no
other code changes.

Production path (post-signature): swap the CSV seed for a POS webhook
(Toast/Square/Lightspeed), move SQLite → Postgres, pin the demo "today"
to the real clock, and add auth in front of the manager routes.
