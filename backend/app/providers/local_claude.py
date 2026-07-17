"""Local `claude` CLI provider (subscription auth — no API key).

Lifted from paperbench/claude_proxy/server.py ``_call_claude``: shells out to
``claude -p`` with all tools disabled so the agentic CLI behaves as a pure LLM
endpoint. This is the default provider and needs only the `claude` binary on PATH.
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from typing import AsyncIterator

from ..config import ensure_claude_sandbox, load_config
from .base import Message, Provider, render_transcript

CLAUDE_SHORT = ("sonnet", "opus", "haiku", "fable")


def _sandbox_env() -> tuple[dict, str]:
    """Return (env, cwd) that isolate the CLI from the user's CLAUDE.md/memory."""
    sb = ensure_claude_sandbox()
    env = os.environ.copy()
    env["HOME"] = str(sb)
    return env, str(sb)


def _pick_model(requested: str | None) -> str:
    cfg = load_config()["providers"]["local_claude"]
    default = cfg.get("model", "sonnet")
    if requested and ("claude" in requested or requested in CLAUDE_SHORT):
        return requested
    return default


def _timeout() -> float:
    return float(load_config()["providers"]["local_claude"].get("timeout", 600))


def _effort() -> str:
    return (load_config()["providers"]["local_claude"].get("effort") or "").strip()


class LocalClaudeProvider(Provider):
    name = "local_claude"

    async def complete(
        self, system: str, messages: list[Message], model: str | None = None
    ) -> tuple[str, dict]:
        prompt = render_transcript(messages)
        model = _pick_model(model)
        cmd = [
            "claude", "-p",
            "--output-format", "json",
            "--no-session-persistence",
            "--tools", "",
            "--model", model,
        ]
        if _effort():
            cmd += ["--effort", _effort()]
        tmp_path = None
        try:
            if system:
                # argv is capped ~128KB; papers easily exceed that -> use a file
                fd, tmp_path = tempfile.mkstemp(prefix="gloss-sys-", suffix=".txt")
                with os.fdopen(fd, "w") as f:
                    f.write(system)
                cmd += ["--system-prompt-file", tmp_path]

            env, cwd = _sandbox_env()
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=cwd,
            )
            try:
                out, err = await asyncio.wait_for(
                    proc.communicate(prompt.encode()), timeout=_timeout()
                )
            except asyncio.TimeoutError:
                proc.kill()
                raise RuntimeError(f"claude CLI timed out after {_timeout()}s")

            if proc.returncode != 0:
                raise RuntimeError(
                    f"claude CLI exited {proc.returncode}: {err.decode()[:2000]}"
                )
            data = json.loads(out.decode())
            if data.get("is_error"):
                raise RuntimeError(str(data.get("result", ""))[:2000])
            usage = data.get("usage", {}) or {}
            norm = {
                "prompt_tokens": usage.get("input_tokens", 0)
                + usage.get("cache_read_input_tokens", 0)
                + usage.get("cache_creation_input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
            }
            norm["total_tokens"] = norm["prompt_tokens"] + norm["completion_tokens"]
            return data.get("result", ""), norm
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    async def stream(
        self, system: str, messages: list[Message], model: str | None = None
    ) -> AsyncIterator[str]:
        """True token streaming via `--output-format stream-json`, with fallback."""
        prompt = render_transcript(messages)
        model = _pick_model(model)
        cmd = [
            "claude", "-p",
            "--output-format", "stream-json",
            "--include-partial-messages",
            "--verbose",
            "--no-session-persistence",
            "--tools", "",
            "--model", model,
        ]
        if _effort():
            cmd += ["--effort", _effort()]
        tmp_path = None
        streamed_any = False
        try:
            if system:
                fd, tmp_path = tempfile.mkstemp(prefix="gloss-sys-", suffix=".txt")
                with os.fdopen(fd, "w") as f:
                    f.write(system)
                cmd += ["--system-prompt-file", tmp_path]

            env, cwd = _sandbox_env()
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=cwd,
            )
            proc.stdin.write(prompt.encode())
            await proc.stdin.drain()
            proc.stdin.close()

            saw_partial = False
            async for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                partial, full = _extract_delta(evt)
                if partial:
                    saw_partial = True
                    streamed_any = True
                    yield partial
                elif full and not saw_partial:
                    # Only use the whole-message text if no partials streamed,
                    # otherwise it duplicates the deltas above.
                    streamed_any = True
                    yield full
            await proc.wait()
        except (FileNotFoundError, RuntimeError):
            streamed_any = False
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        if not streamed_any:
            # Fallback: blocking completion, chunked out.
            text, _ = await self.complete(system, messages, model)
            step = 24
            for i in range(0, len(text), step):
                yield text[i : i + step]


def _extract_delta(evt: dict) -> tuple[str, str]:
    """Return (partial_delta, full_message_text) from a claude stream-json event.

    At most one is non-empty. ``partial`` comes from incremental
    ``content_block_delta`` events; ``full`` from a whole ``assistant`` message.
    """
    t = evt.get("type")
    if t == "stream_event":
        inner = evt.get("event", {})
        if inner.get("type") == "content_block_delta":
            d = inner.get("delta", {})
            if d.get("type") == "text_delta":
                return d.get("text", ""), ""
        return "", ""
    if t == "assistant":
        msg = evt.get("message", {})
        parts = []
        for block in msg.get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "", "".join(parts)
    return "", ""
