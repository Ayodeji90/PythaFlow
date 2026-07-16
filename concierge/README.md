# PythaFlow Concierge

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
