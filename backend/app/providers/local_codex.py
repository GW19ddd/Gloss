"""Local `codex` CLI provider (ChatGPT subscription auth — no API key).

Uses `codex exec` non-interactively as a plain LLM: read-only sandbox, ephemeral
(no session files), a clean working dir (no AGENTS.md to leak), and the final
message captured via `--output-last-message`. Model + reasoning effort are
configurable and passed through the standard codex flags.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from typing import AsyncIterator

from ..config import ensure_codex_sandbox, load_config
from .base import Message, Provider, render_transcript


def _cfg() -> dict:
    return load_config()["providers"]["local_codex"]


class LocalCodexProvider(Provider):
    name = "local_codex"

    async def complete(
        self, system: str, messages: list[Message], model: str | None = None
    ) -> tuple[str, dict]:
        cfg = _cfg()
        model = model or cfg.get("model", "")
        effort = cfg.get("effort", "")
        timeout = float(cfg.get("timeout", 600))
        sandbox = str(ensure_codex_sandbox())

        # codex has no separate system-prompt flag; fold it into the instructions.
        transcript = render_transcript(messages)
        prompt = f"{system}\n\n{transcript}" if system else transcript

        fd, out_path = tempfile.mkstemp(prefix="gloss-codex-", suffix=".txt")
        os.close(fd)
        cmd = [
            "codex", "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "-s", "read-only",
            "-C", sandbox,
            "-o", out_path,
        ]
        if model:
            cmd += ["-m", model]
        if effort:
            cmd += ["-c", f"model_reasoning_effort={effort}"]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, err = await asyncio.wait_for(
                    proc.communicate(prompt.encode()), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                raise RuntimeError(f"codex CLI timed out after {timeout}s")
            if proc.returncode != 0:
                raise RuntimeError(f"codex CLI exited {proc.returncode}: {err.decode()[:2000]}")
            try:
                with open(out_path, "r") as f:
                    text = f.read().strip()
            except OSError:
                text = ""
            if not text:
                raise RuntimeError("codex CLI produced no output")
            return text, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        finally:
            try:
                os.unlink(out_path)
            except OSError:
                pass

    async def stream(
        self, system: str, messages: list[Message], model: str | None = None
    ) -> AsyncIterator[str]:
        # codex exec isn't a token stream; fall back to chunking the completion.
        text, _ = await self.complete(system, messages, model)
        step = 24
        for i in range(0, len(text), step):
            yield text[i : i + step]
