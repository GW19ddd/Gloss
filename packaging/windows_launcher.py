"""Native Windows entry point for the self-contained Gloss executable."""

from __future__ import annotations

import argparse
import multiprocessing
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path


def _resource_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parent.parent


def _prepare_imports() -> None:
    root = _resource_root()
    backend = root / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    os.environ.setdefault("GLOSS_FRONTEND_DIST", str(root / "frontend" / "dist"))


def _port_available(host: str, port: int) -> bool:
    probe_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    try:
        with socket.create_connection((probe_host, port), timeout=0.4):
            return False
    except OSError:
        return True


def _open_when_ready(url: str) -> None:
    health_url = f"{url}/api/health"
    for _ in range(100):
        try:
            with urllib.request.urlopen(health_url, timeout=1) as response:
                if response.status == 200:
                    webbrowser.open(url)
                    return
        except OSError:
            time.sleep(0.1)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="Gloss.exe",
        description="Start the local Gloss AI paper-reading companion.",
    )
    parser.add_argument("--host", default=os.environ.get("GLOSS_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("GLOSS_PORT", "8010"))
    )
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--version", action="version", version="Gloss 1.0.0")
    return parser


def main() -> int:
    multiprocessing.freeze_support()
    args = _parser().parse_args()
    if not 1 <= args.port <= 65535:
        _parser().error("--port must be between 1 and 65535")
    if not _port_available(args.host, args.port):
        print(f"Gloss: port {args.port} on {args.host} is already in use.", file=sys.stderr)
        return 1

    _prepare_imports()
    import uvicorn

    from app.main import app

    browser_host = "127.0.0.1" if args.host in {"0.0.0.0", "::"} else args.host
    url = f"http://{browser_host}:{args.port}"
    print(f"Gloss is running at {url}")
    print("Close this window or press Ctrl+C to stop Gloss.")
    if not args.no_browser:
        threading.Thread(target=_open_when_ready, args=(url,), daemon=True).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
