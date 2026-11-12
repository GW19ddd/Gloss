"""Native Windows entry point for the self-contained Gloss desktop app."""

from __future__ import annotations

import argparse
import ctypes
import json
import logging
import multiprocessing
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any


APP_NAME = "Gloss"
APP_VERSION = "1.0.2"
STARTUP_TIMEOUT_SECONDS = 30
MIN_FALLBACK_PORT = 1024
EXIT_REQUEST_EVENT = "gloss:close-request"

#: The window Gloss opens is titled with this, so a second launch can find it.
WINDOW_TITLE_MARKER = "Gloss"


def _exit_confirmation_enabled() -> bool:
    from app.config import load_config

    return bool(load_config().get("confirm_exit", True))


def _disable_future_exit_confirmation() -> None:
    from app.config import save_config

    save_config({"confirm_exit": False})


class DesktopBridge:
    """Coordinate the native close button with the React confirmation dialog."""

    def __init__(self) -> None:
        self._window: Any | None = None
        self._allow_close = False
        self._prompt_open = False
        self._lock = threading.Lock()

    def bind(self, window: Any) -> None:
        self._window = window

    def on_closing(self) -> bool | None:
        with self._lock:
            if self._allow_close or not _exit_confirmation_enabled():
                return None
            # If React has not loaded yet, do not trap the user in a window that
            # cannot display the custom confirmation dialog.
            if self._window is None or not self._window.events.loaded.is_set():
                return None
            if not self._prompt_open:
                self._prompt_open = True
                threading.Thread(
                    target=self._dispatch_close_request,
                    name="gloss-close-prompt",
                    daemon=True,
                ).start()
        # pywebview cancels a closing event when a handler returns False.
        return False

    def _dispatch_close_request(self) -> None:
        try:
            assert self._window is not None
            self._window.evaluate_js(
                f"window.dispatchEvent(new CustomEvent('{EXIT_REQUEST_EVENT}'))"
            )
        except Exception:
            logging.exception("Could not display the Gloss exit confirmation")
            with self._lock:
                self._prompt_open = False

    def cancel_exit(self) -> bool:
        with self._lock:
            self._prompt_open = False
        return True

    def confirm_exit(self, dont_ask_again: bool = False) -> bool:
        if dont_ask_again:
            try:
                _disable_future_exit_confirmation()
            except Exception:
                logging.exception("Could not disable future exit confirmations")
        with self._lock:
            self._allow_close = True
            self._prompt_open = False
        if self._window is not None:
            self._window.destroy()
        return True


def _ensure_standard_streams() -> None:
    """Give windowed PyInstaller builds safe sinks for CLI-only arguments."""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


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


def _configure_logging() -> Path:
    from app.config import CACHE_DIR

    log_dir = CACHE_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "desktop.log"
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        encoding="utf-8",
    )
    return log_path


def _show_message(message: str, icon: int = 0) -> None:
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, icon)
    else:
        print(f"{APP_NAME}: {message}", file=sys.stderr)


def _show_error(message: str) -> None:
    _show_message(message, 0x10)


def _show_info(message: str) -> None:
    _show_message(message, 0x40)


def _requested_pdf(raw: str | None) -> Path | None:
    """The PDF a file association asked us to open, or None for a plain launch."""
    if not raw:
        return None
    candidate = Path(raw.strip().strip('"')).expanduser()
    if candidate.suffix.lower() != ".pdf" or not candidate.is_file():
        _show_error(f"Gloss can only open PDF files that exist:\n\n{raw}")
        raise SystemExit(2)
    return candidate.resolve()


def _health_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(_health_url(url), timeout=0.5) as response:
            return response.status == 200
    except (OSError, ValueError):
        return False


def _can_receive_files(url: str) -> bool:
    """Whether the instance on ``url`` is a Gloss new enough to take a file.

    Health alone is not enough to accept a hand-off. An older Gloss answers
    ``/api/health`` but has no ``/api/open-file``, so it replies 405 and the
    launcher gives up: to the user, double-clicking a PDF does nothing. Asking
    for the association endpoint distinguishes our own build from anything else
    that happens to be serving on one of these ports.
    """
    try:
        with urllib.request.urlopen(f"{url}/api/file-association", timeout=1.0) as response:
            return response.status == 200
    except (OSError, ValueError):
        return False


def _running_instance() -> str | None:
    """A Gloss server that is already listening, if there is one.

    Windows starts us with only a file path, so the port the running copy ended
    up on is unknown: the small range Gloss prefers is probed in order. Only a
    copy that can actually receive the file counts as running — see
    :func:`_can_receive_files`.
    """
    ports: list[int] = []
    configured = os.environ.get("GLOSS_PORT")
    if configured and configured.isdigit():
        ports.append(int(configured))
    ports.extend(range(8010, 8021))
    for port in dict.fromkeys(ports):
        url = f"http://127.0.0.1:{port}"
        if _health_ok(url) and _can_receive_files(url):
            return url
    return None


def _post_open_file(url: str, path: Path, timeout: float = 60) -> bool:
    """Import ``path`` into a Gloss that is already serving."""
    request = urllib.request.Request(
        f"{url}/api/open-file",
        data=json.dumps({"path": str(path)}).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status == 200
    except (OSError, ValueError):
        logging.info("Could not hand %s to %s", path, url, exc_info=True)
        return False


def _focus_gloss_window() -> None:
    """Raise the window of the Gloss that is already running, best effort.

    A hand-off is invisible without this: the file lands in a window that may be
    behind everything else, and it looks like nothing happened.
    """
    if sys.platform != "win32":
        return
    try:
        user32 = ctypes.windll.user32
        callback = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def visit(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if not length:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            if WINDOW_TITLE_MARKER not in buffer.value:
                return True
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
            return False

        user32.EnumWindows(callback(visit), 0)
    except Exception:
        logging.debug("Could not raise the running Gloss window", exc_info=True)


def _handle_association(args) -> int:
    """Register, unregister or report the PDF association, then exit."""
    from app.file_association import set_registered, status

    try:
        if args.association_status:
            result = status()
        else:
            result = set_registered(args.register)
    except RuntimeError as exc:
        _show_error(str(exc))
        return 1
    except OSError as exc:
        _show_error(f"Windows refused the change:\n\n{exc}")
        return 1

    if not result["supported"]:
        _show_error("PDF file association is only available on Windows.")
        return 1
    if args.association_status:
        _show_info(
            "Gloss is registered as a PDF handler."
            if result["registered"]
            else "Gloss is not registered as a PDF handler."
        )
        return 0
    if result["registered"]:
        _show_info(
            "Gloss now appears under \"Open with\" for PDF files.\n\n"
            "To make it the default: Windows Settings → Apps → Default apps, "
            "then choose Gloss for .pdf."
        )
    else:
        _show_info("Gloss is no longer registered as a PDF handler.")
    return 0


def _port_available(host: str, port: int) -> bool:
    probe_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    try:
        with socket.create_connection((probe_host, port), timeout=0.4):
            return False
    except OSError:
        return True


def _select_available_port(host: str, preferred_port: int) -> int:
    """Use the preferred port when possible, otherwise pick the next free one."""
    candidates = range(preferred_port, 65536)
    if preferred_port > MIN_FALLBACK_PORT:
        candidates = (*candidates, *range(MIN_FALLBACK_PORT, preferred_port))

    for port in candidates:
        if _port_available(host, port):
            return port
    raise RuntimeError("Gloss could not find an available local port.")


def _health_url(url: str) -> str:
    return f"{url}/api/health"


def _wait_until_ready(url: str, server_thread: threading.Thread) -> bool:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline and server_thread.is_alive():
        try:
            with urllib.request.urlopen(_health_url(url), timeout=1) as response:
                if response.status == 200:
                    return True
        except OSError:
            time.sleep(0.1)
    return False


def _start_server(app: Any, host: str, port: int) -> tuple[Any, threading.Thread]:
    import uvicorn

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=False,
        log_config=None,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="gloss-backend", daemon=True)
    thread.start()
    return server, thread


def _stop_server(server: Any, server_thread: threading.Thread) -> None:
    server.should_exit = True
    server_thread.join(timeout=10)


def _run_headless(server: Any, server_thread: threading.Thread) -> int:
    try:
        while server_thread.is_alive():
            server_thread.join(timeout=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        _stop_server(server, server_thread)
    return 0


def _run_desktop(url: str, storage_path: Path) -> None:
    import webview

    storage_path.mkdir(parents=True, exist_ok=True)
    icon_path = _resource_root() / "packaging" / "gloss.ico"
    bridge = DesktopBridge()
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    window = webview.create_window(
        "Gloss · 旁注",
        url=url,
        js_api=bridge,
        width=1500,
        height=950,
        min_size=(1024, 720),
        resizable=True,
        background_color="#111820",
        text_select=True,
        zoomable=True,
    )
    bridge.bind(window)
    window.events.closing += bridge.on_closing
    start_options: dict[str, Any] = {
        "debug": False,
        "storage_path": str(storage_path),
    }
    if sys.platform == "win32":
        # Preserve the packaged Windows application's Edge WebView2 backend.
        start_options.update(gui="edgechromium", icon=str(icon_path))
    webview.start(**start_options)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="Gloss.exe",
        description="Start the Gloss desktop paper-reading companion.",
    )
    parser.add_argument("--host", default=os.environ.get("GLOSS_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("GLOSS_PORT", "8010"))
    )
    parser.add_argument(
        "--headless",
        "--no-window",
        "--no-browser",
        dest="headless",
        action="store_true",
        help="run only the local server (for diagnostics)",
    )
    parser.add_argument(
        "--register",
        action="store_true",
        help="register Gloss as a Windows PDF handler, then exit",
    )
    parser.add_argument(
        "--unregister",
        action="store_true",
        help="remove the Windows PDF handler registration, then exit",
    )
    parser.add_argument(
        "--association-status",
        action="store_true",
        help="report whether the Windows PDF registration is in place, then exit",
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    parser.add_argument(
        "file",
        nargs="?",
        default=None,
        metavar="PDF",
        help="open this PDF (used by the Windows file association)",
    )
    return parser


def main() -> int:
    multiprocessing.freeze_support()
    _ensure_standard_streams()
    args = _parser().parse_args()
    if not 1 <= args.port <= 65535:
        _show_error("Port must be between 1 and 65535.")
        return 2

    _prepare_imports()
    log_path = _configure_logging()

    if args.register or args.unregister or args.association_status:
        return _handle_association(args)

    try:
        from app.config import CACHE_DIR
        from app.main import app

        # Windows hands us a PDF when someone double-clicks one. If Gloss is
        # already serving, hand the file over instead of opening a second copy.
        target = _requested_pdf(args.file)
        if target is not None:
            running = _running_instance()
            if running and _post_open_file(running, target):
                _focus_gloss_window()
                return 0

        requested_port = args.port
        args.port = _select_available_port(args.host, requested_port)
        if args.port != requested_port:
            logging.info(
                "Port %s was occupied; starting Gloss on port %s instead",
                requested_port,
                args.port,
            )

        browser_host = "127.0.0.1" if args.host in {"0.0.0.0", "::"} else args.host
        url = f"http://{browser_host}:{args.port}"
        server, server_thread = _start_server(app, args.host, args.port)
        if not _wait_until_ready(url, server_thread):
            _stop_server(server, server_thread)
            raise RuntimeError("The local Gloss server did not become ready in time.")

        # No copy was running to take the file, so this one imports it and the
        # frontend picks it up from /api/pending-open as soon as it loads.
        if target is not None:
            _post_open_file(url, target)

        if args.headless:
            return _run_headless(server, server_thread)

        try:
            _run_desktop(url, CACHE_DIR / "webview")
        finally:
            _stop_server(server, server_thread)
        return 0
    except Exception as exc:
        logging.exception("Gloss desktop startup failed")
        message = (
            f"Gloss could not start.\n\n{exc}\n\n"
            "Microsoft Edge WebView2 Runtime is required. "
            f"Details were written to:\n{log_path}"
        )
        if args.headless:
            print(message, file=sys.stderr)
        else:
            _show_error(message)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
