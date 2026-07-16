# Sprint Log — PythaFlow Concierge (Phase 0)

## Day 1 — Project skeleton + long-lead kickoff
- Scaffolded `concierge/` service (FastAPI · async SQLAlchemy · Postgres+pgvector · Redis), uv-managed.
- `config.py` Settings; `/health` checks a real DB `SELECT 1` + Redis `PING`.
- docker-compose: `pgvector/pgvector:pg16` + `redis:7` + api; `CREATE EXTENSION vector` on init.
- LLM seam built provider-agnostic: app core → `LLMService` → provider wrapper → vendor API.
  Default provider **NVIDIA NIM** (OpenAI-compatible); `scripts/check_llm.py` smoke test.
- **OPS (owner):** submit Meta Business verification · request WhatsApp BSP · seed 30-day tracker.

**Verified ✅ (Day 1 DONE):** `docker compose up --build` boots api+db+redis;
`GET /health` → 200 `{"status":"ok","db":true,"redis":true,"version":"0.1.0"}`;
`vector` extension present; `ruff` clean; imports OK;
**`check_llm.py` → `✓ nvidia replied`** (NVIDIA NIM live end-to-end).

Notes:
- Fixed a `.env` footgun: inline comments on value lines were parsed as the value
  (broke the key). Comments now on their own lines + a `_strip` validator in config.
- Local DNS couldn't resolve `integrate.api.nvidia.com` (systemd-resolved); fixed
  on the dev machine via resolver flush / public DNS.
- Small free model (llama-3.1-8b) follows instructions loosely — use the
  `quality` tier + guardrails (Day 6) where precision matters.

_Owner tasks (long-lead, not blocking Day 2):_ Meta Business verification,
WhatsApp BSP, seed the 30-day tracker.
