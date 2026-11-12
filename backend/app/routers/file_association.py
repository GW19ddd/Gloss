"""Hand a PDF from outside Gloss to the copy of Gloss that is already running.

Double-clicking a PDF when Gloss is open must not start a second instance: the
shell-side launcher (``Gloss.exe`` or ``gloss.mjs open``) posts the path here,
and the browser that is already looking at Gloss picks it up on its next poll.
That hand-off is a two-step: ``POST /api/open-file`` imports the file and parks
the resulting paper, ``GET /api/pending-open`` hands it over exactly once so a
reload cannot re-open the same paper forever.

Registration of the Windows file association itself lives in
``app.file_association``; this router only exposes it.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from .. import file_association as assoc
from ..library import service, store

router = APIRouter(prefix="/api", tags=["file-association"])

_pending_open: str | None = None
_pending_lock = threading.Lock()


class OpenFileBody(BaseModel):
    path: str


class RegisterBody(BaseModel):
    model_config = {"populate_by_name": True}

    # "register" on the wire; the attribute name stays clear of pydantic's own.
    registered: bool = Field(default=True, alias="register")


def _normalise(path: Path) -> str:
    """Compare paths the way the filesystem does: case-folded on Windows."""
    return os.path.normcase(str(path))


def _resolve_requested_path(raw: str) -> Path:
    candidate = (raw or "").strip().strip('"').strip()
    if not candidate:
        raise HTTPException(400, "a file path is required")
    path = Path(candidate).expanduser()
    if path.suffix.lower() != ".pdf":
        raise HTTPException(400, f"Gloss can only open PDF files: {candidate}")
    if not path.is_file():
        raise HTTPException(400, f"file does not exist: {candidate}")
    return path.resolve()


def _linked_paper(target: Path) -> dict | None:
    """The paper already reading this exact file, so opening twice is idempotent."""
    wanted = _normalise(target)
    for paper in store.list_papers():
        raw = paper.get("source_pdf") or ""
        if not raw.strip():
            continue
        try:
            if _normalise(Path(raw).expanduser().resolve()) == wanted:
                return paper
        except (OSError, ValueError):
            continue
    return None


@router.get("/file-association")
async def get_file_association():
    return assoc.status()


@router.post("/file-association")
async def set_file_association(body: RegisterBody):
    try:
        return assoc.set_registered(body.registered)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    except OSError as exc:
        raise HTTPException(500, f"Windows refused the change: {exc}")


@router.post("/open-file")
async def open_file(body: OpenFileBody):
    """Import the PDF at ``path`` (once per path) and mark it for opening."""
    global _pending_open
    target = _resolve_requested_path(body.path)

    paper = _linked_paper(target)
    if paper is None:
        try:
            paper = await run_in_threadpool(
                service.create_from_pdf_bytes,
                target.read_bytes(),
                {
                    "source": "upload",
                    "title": target.stem,
                    # Remember the original so annotations are written back
                    # into the file the user actually double-clicked.
                    "source_pdf": str(target),
                },
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    with _pending_lock:
        _pending_open = paper["id"]
    return {"paper_id": paper["id"], "title": paper.get("title") or target.stem}


@router.get("/pending-open")
async def pending_open():
    """The paper waiting to be shown, cleared by reading it."""
    global _pending_open
    with _pending_lock:
        paper_id = _pending_open
        _pending_open = None
    return {"paper_id": paper_id}
