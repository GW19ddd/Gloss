from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from app.platform_support import cli_subprocess_loop
from app.providers import local_codex, registry


class _HealthyProvider:
    async def test_connection(self) -> str:
        return "signed in"


class _BrokenProvider:
    async def test_connection(self) -> str:
        raise RuntimeError("not signed in")


def test_registry_records_successful_connection_status(monkeypatch) -> None:
    monkeypatch.setitem(registry._PROVIDERS, "healthy", _HealthyProvider())
    registry.reset_status("healthy")

    result = asyncio.run(registry.test_connection("healthy"))

    assert result["ok"] is True
    assert result["reply"] == "signed in"
    assert registry.provider_statuses()["healthy"]["status"] == "connected"


def test_registry_records_failed_connection_status(monkeypatch) -> None:
    monkeypatch.setitem(registry._PROVIDERS, "broken", _BrokenProvider())
    registry.reset_status("broken")

    result = asyncio.run(registry.test_connection("broken"))

    assert result["ok"] is False
    assert result["error"] == "not signed in"
    assert registry.provider_statuses()["broken"]["status"] == "error"


def test_local_codex_connection_uses_fast_login_status(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict = {}

    class Process:
        returncode = 0

        async def communicate(self):
            return b"Logged in using ChatGPT\n", b""

    async def create(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr(local_codex, "resolve_cli_command", lambda _name: ["codex"])
    monkeypatch.setattr(local_codex, "ensure_codex_sandbox", lambda: tmp_path)
    monkeypatch.setattr(local_codex, "subprocess_group_options", lambda: {"creationflags": 1})
    monkeypatch.setattr(local_codex.asyncio, "create_subprocess_exec", create)

    reply = asyncio.run(local_codex.LocalCodexProvider().test_connection())

    assert captured["args"] == ("codex", "login", "status")
    assert captured["kwargs"]["cwd"] == str(tmp_path)
    assert captured["kwargs"]["creationflags"] == 1
    assert reply == "Logged in using ChatGPT"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows event loop policies")
def test_local_codex_checks_login_on_loops_without_subprocess_support(
    tmp_path: Path, monkeypatch
) -> None:
    """uvicorn --reload installs a Windows selector loop, which cannot spawn
    subprocesses; the CLI check must still run (uvicorn/loops/asyncio.py)."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    async def exercise() -> str:
        loop = asyncio.get_running_loop()
        assert not isinstance(loop, asyncio.ProactorEventLoop)
        monkeypatch.setattr(local_codex, "resolve_cli_command", lambda _name: ["codex"])
        monkeypatch.setattr(local_codex, "ensure_codex_sandbox", lambda: tmp_path)
        monkeypatch.setattr(
            local_codex, "subprocess_group_options", lambda: {"creationflags": 1}
        )
        return await local_codex.LocalCodexProvider().test_connection()

    async def fake_codex_login_status(*_args, **_kwargs):
        class Process:
            returncode = 0

            async def communicate(self):
                return b"Logged in using ChatGPT\n", b""

        return Process()

    monkeypatch.setattr(
        local_codex.asyncio, "create_subprocess_exec", fake_codex_login_status
    )
    try:
        reply = asyncio.run(exercise())
    finally:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    assert reply == "Logged in using ChatGPT"
    assert isinstance(cli_subprocess_loop(), asyncio.ProactorEventLoop)
