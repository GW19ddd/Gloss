"""Moonlight-Local FastAPI application.

Mounts all API routers and serves the built React frontend (SPA) from
``frontend/dist``. One process, one port.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .library import store
from .providers import registry
from .routers import (
    ai,
    annotations,
    citations,
    papers,
    scholar,
    settings,
    skills,
)

app = FastAPI(title="Moonlight-Local", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup() -> None:
    store.init_db()


@app.get("/api/health")
async def health():
    cfg = config.load_config()
    return {
        "status": "ok",
        "provider": cfg.get("provider"),
        "providers": registry.available(),
        "target_language": cfg.get("target_language"),
    }


app.include_router(papers.router)
app.include_router(ai.router)
app.include_router(citations.router)
app.include_router(scholar.router)
app.include_router(annotations.router)
app.include_router(skills.router)
app.include_router(settings.router)


# ---------------------------------------------------------------------------
# Frontend (SPA) — served last so /api/* wins. If the frontend isn't built yet,
# return a helpful message at "/".
# ---------------------------------------------------------------------------
DIST = config.FRONTEND_DIST

if DIST.exists() and (DIST / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=str(DIST / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        # never shadow the API
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "not found"}, status_code=404)
        candidate = DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(DIST / "index.html"))
else:
    @app.get("/")
    async def _not_built():
        return JSONResponse(
            {
                "detail": "Frontend not built yet. Run scripts/setup.sh (or "
                "`cd frontend && npm install && npm run build`). API is live under /api.",
                "api_health": "/api/health",
            }
        )
