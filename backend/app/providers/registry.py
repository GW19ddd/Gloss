"""Provider registry — pick the active LLM provider from config or an override."""
from __future__ import annotations

import asyncio
import time

from ..config import load_config
from .anthropic_api import AnthropicProvider
from .base import Provider, split_system
from .local_claude import LocalClaudeProvider
from .local_codex import LocalCodexProvider
from .openai_api import OpenAIProvider

_PROVIDERS: dict[str, Provider] = {
    "local_claude": LocalClaudeProvider(),
    "local_codex": LocalCodexProvider(),
    "anthropic": AnthropicProvider(),
    "openai": OpenAIProvider(),
}
_STATUSES: dict[str, dict] = {}


def _record_status(name: str, connected: bool, error: str = "") -> None:
    _STATUSES[name] = {
        "status": "connected" if connected else "error",
        "connected": connected,
        "error": error[:400],
        "checked_at": time.time(),
    }


def provider_statuses() -> dict[str, dict]:
    return {
        name: dict(
            _STATUSES.get(
                name,
                {
                    "status": "unknown",
                    "connected": False,
                    "error": "",
                    "checked_at": None,
                },
            )
        )
        for name in _PROVIDERS
    }


def reset_status(name: str) -> None:
    _STATUSES.pop(name, None)


async def test_connection(name: str | None = None) -> dict:
    provider_name = name or load_config().get("provider", "local_claude")
    provider = get_provider(provider_name)
    started = time.monotonic()
    try:
        reply = await asyncio.wait_for(provider.test_connection(), timeout=30)
    except Exception as error:
        message = str(error) or type(error).__name__
        _record_status(provider_name, False, message)
        return {
            "ok": False,
            "provider": provider_name,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error": message[:400],
        }
    _record_status(provider_name, True)
    return {
        "ok": True,
        "provider": provider_name,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "reply": (reply or "").strip()[:200],
    }


def get_provider(name: str | None = None) -> Provider:
    if not name:
        name = load_config().get("provider", "local_claude")
    return _PROVIDERS.get(name, _PROVIDERS["local_claude"])


def available() -> list[str]:
    return list(_PROVIDERS.keys())


async def complete(
    system: str,
    messages: list[dict],
    *,
    provider: str | None = None,
    model: str | None = None,
) -> tuple[str, dict]:
    """Convenience: run a non-streaming completion on the active/selected provider."""
    provider_name = provider or load_config().get("provider", "local_claude")
    p = get_provider(provider_name)
    sys, msgs = split_system(messages, system)
    try:
        result = await p.complete(sys, msgs, model)
    except Exception as error:
        _record_status(provider_name, False, str(error) or type(error).__name__)
        raise
    _record_status(provider_name, True)
    return result


async def stream(
    system: str,
    messages: list[dict],
    *,
    provider: str | None = None,
    model: str | None = None,
):
    provider_name = provider or load_config().get("provider", "local_claude")
    p = get_provider(provider_name)
    sys, msgs = split_system(messages, system)
    connected = False
    try:
        async for chunk in p.stream(sys, msgs, model):
            if not connected:
                _record_status(provider_name, True)
                connected = True
            yield chunk
    except Exception as error:
        _record_status(provider_name, False, str(error) or type(error).__name__)
        raise
    if not connected:
        _record_status(provider_name, True)
