#!/usr/bin/env bash
# Start the Moonlight web app (serves the built frontend + API on one port).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${MOONLIGHT_PORT:-8010}"
HOST="${MOONLIGHT_HOST:-0.0.0.0}"

if [ ! -d "$ROOT/frontend/dist" ]; then
  echo "frontend/dist missing — building it first..."
  (cd "$ROOT/frontend" && npm run build)
fi

echo "🌙 Moonlight-Local → http://$HOST:$PORT"
echo "   (On AutoDL, map this to the 6006 custom-service port, or use SSH port-forwarding.)"
cd "$ROOT/backend"
exec .venv/bin/python -m uvicorn app.main:app --host "$HOST" --port "$PORT"
