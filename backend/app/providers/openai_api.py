"""OpenAI-compatible provider.

Works against real OpenAI, or ANY OpenAI-compatible endpoint — including the
local claude_proxy at http://127.0.0.1:8899/v1. ``trust_env=False`` so localhost
calls don't get routed through the box's SOCKS/HTTP proxy env vars.
"""
from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from ..config import load_config
from .base import Message, Provider


def _cfg() -> dict:
    return load_config()["providers"]["openai"]


class OpenAIProvider(Provider):
    name = "openai"

    def _url(self) -> str:
        base = _cfg().get("base_url", "https://api.openai.com/v1").rstrip("/")
        return f"{base}/chat/completions"

    def _headers(self) -> dict:
        key = _cfg().get("api_key", "") or "sk-none"
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def _messages(self, system: str, messages: list[Message]) -> list[dict]:
        out = []
        if system:
            out.append({"role": "system", "content": system})
        for m in messages:
            if m.get("role") in ("system", "developer"):
                out.append({"role": "system", "content": m.get("content") or ""})
            else:
                out.append({"role": m.get("role", "user"), "content": m.get("content") or ""})
        return out

    async def complete(self, system, messages, model=None):
        c = _cfg()
        body = {
            "model": model or c.get("model", "gpt-4o-mini"),
            "messages": self._messages(system, messages),
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=c.get("timeout", 300), trust_env=False) as client:
            r = await client.post(self._url(), headers=self._headers(), json=body)
            r.raise_for_status()
            data = r.json()
        text = data["choices"][0]["message"].get("content") or ""
        u = data.get("usage", {}) or {}
        usage = {
            "prompt_tokens": u.get("prompt_tokens", 0),
            "completion_tokens": u.get("completion_tokens", 0),
            "total_tokens": u.get("total_tokens", 0),
        }
        return text, usage

    async def stream(self, system, messages, model=None) -> AsyncIterator[str]:
        c = _cfg()
        body = {
            "model": model or c.get("model", "gpt-4o-mini"),
            "messages": self._messages(system, messages),
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=c.get("timeout", 300), trust_env=False) as client:
            async with client.stream(
                "POST", self._url(), headers=self._headers(), json=body
            ) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        evt = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    delta = evt.get("choices", [{}])[0].get("delta", {})
                    piece = delta.get("content")
                    if piece:
                        yield piece
