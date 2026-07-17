"""Provider registry — pick the active LLM provider from config or an override."""
from __future__ import annotations

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
    p = get_provider(provider)
    sys, msgs = split_system(messages, system)
    return await p.complete(sys, msgs, model)


async def stream(
    system: str,
    messages: list[dict],
    *,
    provider: str | None = None,
    model: str | None = None,
):
    p = get_provider(provider)
    sys, msgs = split_system(messages, system)
    async for chunk in p.stream(sys, msgs, model):
        yield chunk
