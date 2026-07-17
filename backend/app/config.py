"""Configuration + on-disk paths for Moonlight-Local.

Everything lives under the project's ``backend/data`` dir (which sits on the fast
data disk via the project symlink). Provider settings are persisted to
``data/config.json`` and edited from the Settings UI / CLI.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_BACKEND_DIR = Path(__file__).resolve().parent.parent          # backend/
DATA_DIR = Path(os.environ.get("MOONLIGHT_DATA_DIR", _BACKEND_DIR / "data")).resolve()
PAPERS_DIR = DATA_DIR / "papers"
UPLOADS_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "moonlight.db"
CONFIG_PATH = DATA_DIR / "config.json"

for _d in (DATA_DIR, PAPERS_DIR, UPLOADS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Directory served as the built frontend (populated by `vite build`).
FRONTEND_DIST = (_BACKEND_DIR.parent / "frontend" / "dist").resolve()

# ---------------------------------------------------------------------------
# Isolated HOME for the `claude` CLI subprocess.
#
# The CLI otherwise auto-discovers the user's ~/.claude/CLAUDE.md + memory +
# project context, which leaks into paper answers. We run it under a sandbox
# HOME that symlinks ONLY the auth files (credentials + config), so it keeps the
# subscription (OAuth) but sees no CLAUDE.md / memory / settings.
# ---------------------------------------------------------------------------
CLAUDE_SANDBOX_HOME = (_BACKEND_DIR.parent / ".claude-home").resolve()


def ensure_claude_sandbox() -> Path:
    """Create/refresh the sandbox HOME for the claude CLI. Idempotent."""
    import os as _os
    from pathlib import Path as _Path

    real_home = _Path(_os.path.expanduser("~"))
    sb = CLAUDE_SANDBOX_HOME
    (sb / ".claude").mkdir(parents=True, exist_ok=True)

    def _link(src: Path, dst: Path) -> None:
        try:
            if src.exists() and not dst.exists():
                dst.symlink_to(src)
        except OSError:
            pass

    _link(real_home / ".claude" / ".credentials.json", sb / ".claude" / ".credentials.json")
    _link(real_home / ".claude.json", sb / ".claude.json")
    return sb

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
HOST = os.environ.get("MOONLIGHT_HOST", "0.0.0.0")
PORT = int(os.environ.get("MOONLIGHT_PORT", "8010"))

# ---------------------------------------------------------------------------
# Provider / app configuration (persisted)
# ---------------------------------------------------------------------------
DEFAULT_CONFIG: dict[str, Any] = {
    # active LLM provider: "local_claude" | "anthropic" | "openai"
    "provider": "local_claude",
    # language the AI ANSWERS in — summaries, explanations, chat, highlight notes
    "output_language": "中文 (Simplified Chinese)",
    # default TARGET language for the translate feature
    "target_language": "中文 (Simplified Chinese)",
    "providers": {
        "local_claude": {
            # short names the claude CLI understands, or full claude model ids
            "model": "sonnet",
            "timeout": 600,
        },
        "anthropic": {
            "model": "claude-sonnet-4-5",
            "api_key": "",
            "base_url": "https://api.anthropic.com",
            "timeout": 300,
        },
        "openai": {
            # Works against real OpenAI, or any OpenAI-compatible endpoint,
            # e.g. the local claude_proxy at http://127.0.0.1:8899/v1
            "model": "gpt-4o-mini",
            "api_key": "",
            "base_url": "https://api.openai.com/v1",
            "timeout": 300,
        },
    },
}

_lock = threading.Lock()


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict[str, Any]:
    """Return the persisted config merged over defaults (so new keys appear)."""
    if CONFIG_PATH.exists():
        try:
            user = json.loads(CONFIG_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            user = {}
    else:
        user = {}
    return _deep_merge(DEFAULT_CONFIG, user)


def save_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Persist config (merged over the current one) and return the result."""
    with _lock:
        merged = _deep_merge(load_config(), cfg)
        CONFIG_PATH.write_text(json.dumps(merged, indent=2, ensure_ascii=False))
    return merged


def output_language() -> str:
    """Language the AI should answer in (summaries / explain / chat)."""
    return load_config().get("output_language", "中文 (Simplified Chinese)")


def public_config() -> dict[str, Any]:
    """Config with secrets masked, safe to send to the browser."""
    cfg = load_config()
    out = json.loads(json.dumps(cfg))  # deep copy
    for name, p in out.get("providers", {}).items():
        if p.get("api_key"):
            p["api_key"] = "set"
        else:
            p["api_key"] = ""
    return out
