# Day 01 — Walkthrough, Logic & Manual Testing

Everything we built on Day 1, *why* it's built that way, and how to test each
piece by hand. Day 1's job is not to be smart — it's to stand up a **correct,
observable skeleton** that the rest of the 30 days bolts onto.

---

## 0. The mental model

A concierge is **I/O-bound**: almost everything it does is *wait* on something
over a network — the database, Redis, the LLM, later the phone/WhatsApp APIs. So
the whole service is **async** end to end. One process can then juggle hundreds
of concurrent conversations while they're all waiting, instead of one-at-a-time.

Three ideas drive every Day-1 decision:
1. **One typed source of truth for config** (`config.py`) — nothing reads the
   environment directly.
2. **Health means "can I actually reach my dependencies?"** — not "did the
   process start."
3. **The app core never imports a vendor SDK** — it talks to a stable
   `LLMService`; vendors sit behind swappable wrappers.

---

## 1. Project scaffold & tooling

**Files:** `pyproject.toml`, `.gitignore`, `.dockerignore`, `ruff.toml` (in
pyproject), `.env.example`

**What & why:**
- **`uv`** manages the virtualenv and dependencies (fast, reproducible). We mark
  the project `package = false` in `pyproject.toml` because this is an
  *application*, not a library to be built/published — `uv` just installs the
  dependencies into `.venv`.
- **`ruff`** is linter + formatter in one; keeps the code consistent from line 1.
- **`.env` is gitignored** — secrets never enter git. `.env.example` is the
  committed template.

**Test it:**
```bash
cd concierge
uv sync --extra dev          # install runtime + dev deps
uv run ruff check .          # -> "All checks passed!"
uv run python -c "import app.main; print('imports OK')"
```

---

## 2. Configuration — `app/config.py`

**What:** a `Settings` class (pydantic-settings) that loads from environment
variables and the `.env` file, with typed fields and defaults.

**The logic:**
- **12-factor config:** behaviour comes from the environment, so the *same image*
  runs in dev/staging/prod with different `.env` values. No code changes to switch
  a model or a database.
- **One source of truth:** every module calls `get_settings()`; nothing reads
  `os.environ` directly. That makes config testable and discoverable.
- **`@lru_cache`** makes `get_settings()` a singleton — parsed once, reused.
- **`_strip` validator:** we added a `field_validator` that trims whitespace off
  `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_PROVIDER`. This is the scar from the
  Day-1 bug where an inline comment in `.env` got read as the key (see §11).

**Test it:**
```bash
# print the resolved settings (secrets shown only as booleans)
uv run python -c "
from app.config import get_settings
s = get_settings()
print('provider   :', s.LLM_PROVIDER)
print('model_fast :', s.LLM_MODEL_FAST)
print('db_url     :', s.DATABASE_URL)
print('api_key set:', bool(s.LLM_API_KEY))
"
```

---

## 3. Local infrastructure — `docker-compose.yml`, `Dockerfile`, `init/`

**What:** three containers — `db` (Postgres **with pgvector**), `redis`, and
`api` (our app) — wired together.

**The logic:**
- **`pgvector/pgvector:pg16`** instead of plain Postgres: we need the `vector`
  type for the knowledge base (RAG) from Day 5. Installing it now means the
  database is ready when we get there. `init/01_extensions.sql` runs once on first
  boot and does `CREATE EXTENSION IF NOT EXISTS vector`.
- **Healthchecks + `depends_on: condition: service_healthy`:** the `api` container
  refuses to start until Postgres answers `pg_isready` and Redis answers `PING`.
  This removes the classic "app crashes on boot because the DB isn't up yet" race.
- **Named volume `pgdata`:** the database survives `docker compose down`. Use
  `down -v` only when you want a clean slate.
- **Env override in compose:** on the host, `DATABASE_URL` points at
  `localhost`; inside the compose network the `api` service overrides it to the
  service name `db`. Same code, different wiring — that's config doing its job.

**Test it:**
```bash
# start just the datastores
docker compose up -d db redis
docker compose ps                       # both should be "healthy"

# prove pgvector is installed
docker exec concierge-db-1 psql -U concierge -d concierge -tAc \
  "SELECT extname FROM pg_extension WHERE extname='vector';"    # -> vector

# prove redis is alive
docker exec concierge-redis-1 redis-cli ping                    # -> PONG

# full stack (build + run the api too)
docker compose up --build                # ctrl-C to stop
```

---

## 4. Database layer — `app/db.py`

**What:** an async SQLAlchemy **engine**, a **session factory**
(`SessionLocal`), the declarative **`Base`** (models hang off it on Day 2), and a
`ping_db()` helper.

**The logic:**
- **`create_async_engine` + `asyncpg`:** non-blocking Postgres access so a slow
  query doesn't freeze the event loop.
- **`pool_pre_ping=True`:** before handing out a pooled connection, SQLAlchemy
  checks it's still alive — avoids "server closed the connection unexpectedly"
  after idle periods.
- **`ping_db()`** runs `SELECT 1` and returns a bool. It's deliberately
  exception-swallowing: health reporting must never itself throw.

**Test it:**
```bash
uv run python -c "
import asyncio
from app.db import ping_db
print('db reachable:', asyncio.run(ping_db()))
"
```

---

## 5. Redis — `app/services/redis.py`

**What:** a shared async Redis client + `ping_redis()`.

**The logic:** Redis will hold **hot conversation state** (Day 4) and later job
queues. `@lru_cache` gives us one client instance for the process. Like the DB
ping, `ping_redis()` never raises.

**Test it:**
```bash
uv run python -c "
import asyncio
from app.services.redis import ping_redis
print('redis reachable:', asyncio.run(ping_redis()))
"
```

---

## 6. Dependencies — `app/deps.py`

**What:** FastAPI dependency providers `get_db()` (a request-scoped session that
auto-closes) and `get_redis()`.

**The logic:** FastAPI's dependency injection means a route just declares
`db: AsyncSession = Depends(get_db)` and gets a clean, auto-closed session. No
manual open/close in every handler; no leaked connections. (Routes start using
these on Day 3.)

---

## 7. Health endpoint — `app/routers/health.py`

**What:** `GET /health` → checks the DB and Redis, returns their status.

**The logic:** a health check that returns `200` no matter what is useless. Ours
actually pings both datastores, so a load balancer / `docker` / a monitor can
tell **readiness** (can it serve traffic?) from a bare process being alive. If
either dependency is down, `status` becomes `"degraded"` and the booleans tell
you which one.

**Test it:**
```bash
# with app running on :8000
curl -s localhost:8000/health | python3 -m json.tool
# -> {"status":"ok","db":true,"redis":true,"version":"0.1.0"}

# see it report degraded: stop redis, then call again
docker compose stop redis
curl -s localhost:8000/health           # -> "status":"degraded","redis":false
docker compose start redis
```

---

## 8. App factory + lifespan — `app/main.py`

**What:** `create_app()` builds the `FastAPI` instance and mounts routers; a
**lifespan** context manager runs on startup/shutdown.

**The logic:**
- **App factory pattern:** building the app in a function (not at import time as a
  side effect) makes it testable — tests can build a fresh app with overrides.
- **Lifespan:** on startup we log whether DB/Redis are reachable (fast feedback in
  the logs); on shutdown we **dispose the engine and close Redis** so connections
  don't leak. We *log* reachability rather than *crash* — a temporarily-down
  dependency should surface in `/health`, not prevent boot.

**Test it:**
```bash
uv run uvicorn app.main:app --reload
# watch the startup log:
#   INFO concierge: db reachable:    True
#   INFO concierge: redis reachable: True
```
FastAPI also gives you free interactive docs — open these in a browser:
- **http://localhost:8000/docs** — Swagger UI (try `/health` from the browser)
- **http://localhost:8000/openapi.json** — the machine-readable API schema

---

## 9. The LLM seam — `app/llm/`

This is the part we invested in deliberately. **Three layers, fully separated:**

```
app core ──depends only on──▶ LLMService ──▶ Provider wrapper ──▶ vendor API
 (routers,                    (service.py)   (providers/*.py)     (NVIDIA NIM)
  orchestrator)               STABLE          SWAPPABLE
```

- **`base.py`** — the vocabulary and the contract: `LLMMessage`, `LLMResult`, and
  the `LLMProvider` ABC. **No vendor import here.**
- **`providers/openai_compatible.py`** — the *only* file that imports a vendor SDK
  (`openai`). It works with **any OpenAI-compatible API** — NVIDIA NIM, OpenAI,
  Groq, Mistral, local Ollama — just by pointing `base_url` at them.
- **`service.py` (`LLMService`)** — the stable, app-facing interface. It maps a
  quality **tier** (`"fast"` / `"quality"`) to a concrete model and delegates to
  whatever provider is configured. **The app core depends only on this.**
- **`factory.py`** — reads `Settings`, picks the provider, resolves its base URL,
  returns a ready `LLMService`.

**Why this matters:**
- **Swap vendors by editing `.env`** — `LLM_PROVIDER=groq` and you're on Groq. No
  app-core change, no caller change.
- **Add a non-OpenAI vendor (e.g. Anthropic)** = one new wrapper file + one branch
  in `factory.py`. Nothing else moves.
- **Testable:** you can hand the orchestrator a fake `LLMProvider` in tests — no
  network, no key.
- **NVIDIA today** because NIM speaks the OpenAI protocol, so the
  `OpenAICompatibleProvider` already covers it.

**Test it (Python, exercises the whole seam):**
```bash
uv run python -c "
import asyncio
from app.llm.factory import build_llm_service
async def go():
    svc = build_llm_service()
    print('provider:', svc.provider_name, '| model:', svc.model_for('fast'))
    reply = await svc.generate('Reply with one word: PONG', tier='fast',
                               system='Reply with one word only.')
    print('reply:', reply)
    await svc.aclose()
asyncio.run(go())
"
```

**Test provider switching without touching code:**
```bash
# temporarily point at a different OpenAI-compatible vendor
LLM_PROVIDER=groq LLM_API_KEY=gsk_... LLM_MODEL_FAST=llama-3.1-8b-instant \
  uv run python scripts/check_llm.py
```

---

## 10. LLM smoke test — `scripts/check_llm.py`

**What:** a one-shot script that runs `app core → LLMService → provider → vendor`
and prints the reply.

**The logic:** it fails *loudly and specifically* — no key vs malformed key vs
call-failed are three different messages, so you know exactly what to fix. It's
the canonical "is the LLM wired up?" check we'll rerun all sprint.

**Test it:**
```bash
uv run python scripts/check_llm.py
#   ✓ nvidia replied: 'PONG'            (key set + DNS working)
#   ✗ LLM_API_KEY is not set. ...        (no key)
#   ✗ LLM call failed: APIConnection...  (network/DNS problem)
```

**Test the vendor directly with `curl`** (bypasses our code entirely — useful to
tell "is it them or us?"). If your local DNS can't resolve the host, add
`--resolve integrate.api.nvidia.com:443:<ip-from-8.8.8.8>`:
```bash
KEY=$(grep '^LLM_API_KEY=' .env | cut -d= -f2- | tr -d '[:space:]')
curl -s https://integrate.api.nvidia.com/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"meta/llama-3.1-8b-instruct",
       "messages":[{"role":"user","content":"Say PONG"}],
       "max_tokens":10}' | python3 -m json.tool
# HTTP 200 + a completion  => key + endpoint + model all good
```

---

## 11. `.env` — and the Day-1 bug worth remembering

The original `.env.example` had **inline comments on value lines**:
```
LLM_API_KEY=          # NVIDIA: nvapi-...
```
The dotenv parser read the *comment* as the value, so the app thought a key was
set and tried to call the API with garbage. **Lesson:** in `.env`, keep comments
on their own lines and put values alone:
```
# NVIDIA key (starts with nvapi-)
LLM_API_KEY=nvapi-xxxxxxxx
```
We also added the `_strip` validator (§2) as a belt-and-suspenders guard.

---

## 12. One-shot: bring it all up and verify

```bash
cd concierge
cp .env.example .env            # then set LLM_API_KEY=nvapi-...
uv sync --extra dev

# infra + app
docker compose up -d db redis
uv run uvicorn app.main:app --reload &      # or: docker compose up --build

# verify
curl -s localhost:8000/health | python3 -m json.tool      # status ok, db+redis true
uv run python scripts/check_llm.py                         # ✓ nvidia replied: 'PONG'

# open in a browser
#   http://localhost:8000/health
#   http://localhost:8000/docs
```

**Day-1 is "done" when:** `/health` is `ok` with `db` and `redis` both `true`,
and `check_llm.py` prints `PONG`.
