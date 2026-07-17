"""Settings: view/update provider config (secrets masked on read)."""
from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter
from pydantic import BaseModel

from .. import config
from ..providers import registry

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsPatch(BaseModel):
    provider: str | None = None
    output_language: str | None = None
    target_language: str | None = None
    providers: dict | None = None


@router.get("")
async def get_settings():
    return {
        "config": config.public_config(),
        "available_providers": registry.available(),
    }


@router.post("")
async def update_settings(body: SettingsPatch):
    patch: dict = {}
    if body.provider:
        patch["provider"] = body.provider
    if body.output_language:
        patch["output_language"] = body.output_language
    if body.target_language:
        patch["target_language"] = body.target_language
    if body.providers:
        # ignore masked api_key sentinel so we don't overwrite real keys with "set"
        cleaned = {}
        for name, p in body.providers.items():
            pc = dict(p)
            if pc.get("api_key") in ("set", ""):
                pc.pop("api_key", None)
            cleaned[name] = pc
        patch["providers"] = cleaned
    config.save_config(patch)
    return {"config": config.public_config()}


class TestBody(BaseModel):
    provider: str | None = None


@router.post("/test")
async def test_provider(body: TestBody):
    """Ping a provider with a tiny completion to check it's reachable/authenticated."""
    provider = body.provider or config.load_config().get("provider")
    t0 = time.time()
    try:
        text, _ = await asyncio.wait_for(
            registry.complete(
                "You are a connectivity check. Reply with exactly: OK",
                [{"role": "user", "content": "ping"}],
                provider=provider,
            ),
            timeout=90,
        )
        return {
            "ok": True,
            "provider": provider,
            "latency_ms": int((time.time() - t0) * 1000),
            "reply": (text or "").strip()[:80],
        }
    except asyncio.TimeoutError:
        return {"ok": False, "provider": provider, "error": "timed out after 90s"}
    except Exception as e:  # noqa: BLE001 — surface any provider error to the UI
        return {"ok": False, "provider": provider, "error": str(e)[:400]}
