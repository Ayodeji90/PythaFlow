# HAND_OFF — manual ops steps (do these in your terminal)

Everything here needs your shell / sudo / real credentials — I (Buffy) can't run
them from my side. None of it blocks *writing* more code; it blocks **running**
the DB-dependent tests and the **live demos**. Work through it whenever you're
ready. Total ~10 minutes if the network cooperates.

## 0 · The plan in one glance

| Step | Command | Why |
|---|---|---|
| 1 | Start Postgres + Redis | infra for every DB test + the live demo |
| 2 | Paste secrets into `.env` | LLM key + WhatsApp sandbox credentials |
| 3 | `alembic upgrade head` | build the schema |
| 4 | `uv run python scripts/seed.py` | seed Demo Bistro + channels |
| 5 | Full test suite + `alembic check` | prove everything's green |
| 6 | Eval `--live` recording | real baseline (was 0.0%) |
| 7 | WhatsApp live demo | guest books on the sandbox number |

## 1 · Start Postgres + Redis (Docker)

Your `sudo docker compose up -d db redis` failed with a **DNS timeout** pulling
the images:

```
failed to copy: … lookup production.cloudfront.docker.com on 127.0.0.53:53: read udp …:53: i/o timeout
```

That's a flaky systemd-resolved, not a code problem (connectivity is fine —
verified). Try in order until one works:

```bash
cd ~/PythaFlow/concierge

# 1a. just retry — transient DNS blips usually clear
sudo docker compose up -d db redis

# 1b. still failing? pull each image separately
sudo docker pull pgvector/pgvector:pg16
sudo docker pull redis:7
sudo docker compose up -d db redis

# 1c. still failing? restart the resolver and retry
sudo resolvectl flush-caches
sudo systemctl restart systemd-resolved
sudo docker pull pgvector/pgvector:pg16 && sudo docker pull redis:7

# 1d. still failing? point Docker at public DNS and restart the daemon
sudo mkdir -p /etc/docker
echo '{ "dns": ["8.8.8.8", "1.1.1.1"] }' | sudo tee /etc/docker/daemon.json
sudo systemctl restart docker
sudo docker pull pgvector/pgvector:pg16 && sudo docker pull redis:7
```

**Verify:** `sudo docker ps` shows `db` and `redis` healthy.

> Optional but recommended (avoids typing `sudo` forever):
> `sudo usermod -aG docker $USER` then **log out and back in**.

## 2 · Secrets in `.env`

`.env` already exists (copied from `.env.example`). Fill in the blanks:

```bash
cd ~/PythaFlow/concierge && nano .env
```

| Key | Where to get it |
|---|---|
| `LLM_API_KEY` | NVIDIA build.nvidia.com free API key (starts `nvapi-`) — already validated earlier in this project |
| `EMBED_API_KEY` | same key if same vendor, else blank (falls back to LLM key) |
| `WHATSAPP_BSP` | `meta` (Cloud API / 360dialog / Twilio sandbox all proxy it) or `mock` for no-network |
| `WHATSAPP_TOKEN` | BSP access token (360dialog/Twilio sandbox page) |
| `WHATSAPP_PHONE_ID` | your sandbox business number id — **must equal the `Channel.external_id`** the seed uses (`1000` for demo) or change the seed |
| `WHATSAPP_VERIFY_TOKEN` | any string you choose; you paste the same string into the BSP webhook config |
| `WHATSAPP_APP_SECRET` | BSP app secret — used to verify `X-Hub-Signature-256` |
| `STAFF_TOKEN` | your own secret for the staff endpoints (any string) |

## 3 · Build the schema + seed

```bash
cd ~/PythaFlow/concierge
export PATH="$HOME/.local/bin:$PATH"

uv run alembic upgrade head
uv run python scripts/seed.py        # idempotent — re-running is a no-op
uv run python scripts/ingest_kb.py   # ingest Demo Bistro KB chunks for RAG
```

## 4 · Verify everything

```bash
uv run ruff check .
uv run pytest -q                    # expect ~100+ green incl. Day 15/16 WhatsApp tests
uv run alembic check                # expect "No new upgrade operations detected"
```

If `uv` isn't found: `curl -LsSf https://astral.sh/uv/install.sh | sh`

## 5 · Eval baseline (Day 13 harness was never live-scored)

```bash
uv run python -m evals.runner --live --baseline
# then commit evals/recordings/*.yaml + evals/BASELINE.md updates
```

## 6 · Live WhatsApp demo (Day 15/16)

1. Point your BSP sandbox webhook at the running app:
   `http://<your-host>/webhooks/whatsapp` with the verify token from `.env`.
2. Run the app: `uv run uvicorn app.main:app --port 8000` (needs step 1 done).
3. Message the sandbox number from your phone — the concierge answers.
4. Outbound confirmations/reminders go out automatically; outside the 24h
   window they use templates (next step).

## 7 · Submit WhatsApp templates (long-lead, start now)

Approval takes days — see `concierge/docs/whatsapp_templates.md`. Submit
`booking_confirmed` / `booking_reminder` / `booking_updated` in the BSP
dashboard with the exact variable orders listed there.

---

## What's built and awaiting this hand-off

- **Day 14** closed in `SPRINT_LOG.md` (retro + Week-3 backlog groomed).
- **Day 15** — WhatsApp adapter: client seam (`meta`/`mock`), webhook
  (`GET` challenge + `POST` with HMAC), `to_inbound()` → shared pipeline,
  outbound via the `notify()` subscriber. **Zero brain changes** (a structural
  test enforces it). 8 tests written; 4 pass without Postgres, 4 need it.
- **Day 16** — WhatsApp hardening: 24h service-window logic, template registry
  (text in-window / template out), delivery+read receipts persisted on
  `Message.meta`, bounded retry with idempotent delivery. Tests in
  `tests/test_whatsapp_hardening.py`.
- **Day 17** — staff console (view): shared `X-Staff-Token` auth + `/console`
  page, conversations list + transcript API (tenant-scoped), SSE live updates.
  Open it at `/console?token=YOUR_TOKEN` (see step 2 for the token). Tests in
  `tests/test_console_views.py`.
- **Still TODO:** console approvals queue + live takeover (Day 18),
  escalation + notifications (Day 19), KB/config editor (Day 20),
  Week-3 closeout (Day 21).

**When you've done step 4**, tell me the pytest + alembic output and I'll take
it from there (and commit nothing without your OK).
