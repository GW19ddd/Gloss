#!/usr/bin/env bash
# Dev mode: backend with autoreload (:8010) + Vite dev server (:5173, proxies /api).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT/backend"
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "${MOONLIGHT_PORT:-8010}" --reload &
BACK=$!
trap 'kill $BACK 2>/dev/null' EXIT

cd "$ROOT/frontend"
echo "🌙 dev: backend :8010 (reload) + vite :5173  → open http://localhost:5173"
npm run dev
