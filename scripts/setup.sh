#!/usr/bin/env bash
# One-shot setup: backend venv + deps, frontend deps + build.
# All caches/artefacts stay on the data disk (system disk is small).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DISK="${MOONLIGHT_DATA_DISK:-/root/autodl-tmp}"

export PIP_CACHE_DIR="$DATA_DISK/.pip_cache"
export npm_config_cache="$DATA_DISK/.npm-cache"
export TMPDIR="$DATA_DISK/.npm-cache/tmp"
mkdir -p "$TMPDIR" "$PIP_CACHE_DIR"

echo "==> backend venv"
cd "$ROOT/backend"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt
deactivate

echo "==> frontend deps + build"
cd "$ROOT/frontend"
npm install --no-fund --no-audit
npm run build

echo "==> done. Start with:  scripts/run.sh   (or  ./moonlight serve )"
