"""Provider interface + shared message rendering.

Internal message format is OpenAI-style: a list of ``{"role", "content"}`` dicts
plus a separate ``system`` string. Each provider adapts that to its transport.
"""
from __future__ import annotations

from typing import AsyncIterator

Message = dict  # {"role": "user"|"assistant"|"system", "content": str}


def render_transcript(messages: list[Message]) -> str:
    """Flatten a conversation into a single text prompt (for the claude CLI).

    Mirrors the claude_proxy behaviour: a lone user turn is passed verbatim,
    otherwise turns are labelled and a trailing ``[Assistant]:`` cue is appended.
    """
    convo: list[str] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content") or ""
        if isinstance(content, list):  # multimodal -> keep text blocks
            content = "\n".join(
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        if role in ("system", "developer"):
            continue  # system handled separately
        elif role == "assistant":
            convo.append(f"[Assistant]:\n{content}")
        else:
            convo.append(f"[User]:\n{content}")
    if len(convo) == 1 and convo[0].startswith("[User]:\n"):
        return convo[0][len("[User]:\n") :]
    return "\n\n".join(convo) + "\n\n[Assistant]:"


def split_system(messages: list[Message], system: str | None) -> tuple[str, list[Message]]:
    """Pull any system/developer messages into the system string."""
    sys_parts = []
    if system:
        sys_parts.append(system)
    rest = []
    for m in messages:
        if m.get("role") in ("system", "developer"):
            c = m.get("content") or ""
            if c:
                sys_parts.append(c)
        else:
            rest.append(m)
    return "\n\n".join(sys_parts), rest


class Provider:
    """Abstract LLM provider."""

    name = "base"

    async def test_connection(self) -> str:
        """Run the smallest provider request that proves the connection works."""
        text, _ = await self.complete(
            "You are a connectivity check. Reply with exactly: OK",
            [{"role": "user", "content": "ping"}],
        )
        return (text or "").strip()

    async def stream(
        self, system: str, messages: list[Message], model: str | None = None
    ) -> AsyncIterator[str]:
        """Yield text deltas. Default: chunk the non-stream completion."""
        text, _ = await self.complete(system, messages, model)
        # emit in modest chunks so the UI feels live
        step = 24
        for i in range(0, len(text), step):
            yield text[i : i + step]

    async def complete(
        self, system: str, messages: list[Message], model: str | None = None
    ) -> tuple[str, dict]:
        """Return (text, usage_dict). Must be implemented by subclasses."""
        raise NotImplementedError
