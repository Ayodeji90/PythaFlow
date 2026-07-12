#!/usr/bin/env bash
# Run the whole Graycliff platform with ONE command:
#
#   ./dev.sh
#
# Endpoints once it's up:
#   http://localhost:8000/site    graycliff.com mockup + concierge widget
#   http://localhost:5173         guest menu · /dashboard · /knowledge · /voice · /marketing
#   http://localhost:8000/docs    API reference (Swagger)
#
# Both services hot-reload on code changes. Ctrl+C stops everything.
set -euo pipefail
cd "$(dirname "$0")"

ROOT="$(cd .. && pwd)"
UVICORN="$ROOT/.venv/bin/uvicorn"

cleanup() { kill $(jobs -p) 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "▸ backend   http://localhost:8000   (mockup at /site · API docs at /docs)"
(cd backend && "$UVICORN" app.main:app --port 8000 --reload --reload-dir app) &

echo "▸ frontend  http://localhost:5173"
(cd frontend && npm run dev -- --port 5173) &

wait
