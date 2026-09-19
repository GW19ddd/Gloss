"""Locate a paper's *original* PDF on disk — typically its Zotero attachment.

Gloss copies every imported PDF into its own data directory, so it normally has
no idea where the file the user actually keeps lives. To write annotations into
that original (Zotero's copy, a folder of papers, …) we either take an explicit
path from the user, or search a few known directories for a filename that looks
like the paper.
"""
from __future__ import annotations

import re
from pathlib import Path

from .. import config
from ..library import store

#: Safety valve: a Zotero storage folder can hold thousands of files.
MAX_FILES_SCANNED = 20_000

_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


def _default_dirs() -> list[Path]:
    """Zotero's usual storage locations, when present."""
    home = Path.home()
    candidates = (
        home / "Zotero" / "storage",
        home / "Documents" / "Zotero" / "storage",
        home / "Zotero Library" / "storage",
    )
    return [p for p in candidates if p.is_dir()]


def search_dirs() -> list[Path]:
    """Configured directories plus the default Zotero locations."""
    raw = config.load_config().get("source_pdf_dirs") or []
    dirs: list[Path] = []
    for item in raw:
        try:
            path = Path(str(item)).expanduser()
        except (OSError, ValueError):
            continue
        if path.is_dir() and path not in dirs:
            dirs.append(path)
    for path in _default_dirs():
        if path not in dirs:
            dirs.append(path)
    return dirs


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_SPLIT.split((text or "").lower()) if len(t) >= 4}


def _score(paper: dict, path: Path) -> int:
    """How strongly a filename looks like this paper (0 = no match)."""
    stem = path.stem.lower()
    name_tokens = set(_TOKEN_SPLIT.split(stem))

    score = 4 * len(_tokens(paper.get("title", "")) & name_tokens)

    year = str(paper.get("year") or "").strip()
    if year and year in stem:
        score += 3

    for author in (paper.get("authors") or [])[:3]:
        parts = str(author).split()
        surname = parts[-1].lower() if parts else ""
        if len(surname) >= 4 and surname in stem:
            score += 3

    return score


def find_candidates(paper: dict, limit: int = 8) -> list[dict]:
    """Best-matching PDFs for ``paper`` across the search directories."""
    if not paper:
        return []
    scored: list[tuple[int, Path]] = []
    scanned = 0
    for base in search_dirs():
        try:
            iterator = base.rglob("*.pdf")
        except OSError:
            continue
        try:
            for path in iterator:
                scanned += 1
                if scanned > MAX_FILES_SCANNED:
                    break
                score = _score(paper, path)
                if score > 0:
                    scored.append((score, path))
        except OSError:
            continue
        if scanned > MAX_FILES_SCANNED:
            break

    scored.sort(key=lambda item: (-item[0], str(item[1]).lower()))
    return [
        {"path": str(path), "name": path.name, "score": score}
        for score, path in scored[:limit]
    ]


def already_linked(paper_id: str) -> Path | None:
    return store.source_pdf_path(paper_id)
