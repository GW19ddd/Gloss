"""Mirror Gloss's outline into the PDF's own bookmark tree.

An AI-cleaned (or translated) outline lives in Gloss's database, so it is
invisible the moment the PDF leaves the app. Writing it into the file's
``/Outlines`` makes it the paper's real table of contents — Acrobat, Preview,
Zotero and Skim all show it in their sidebar.

Bookmarks are replaced wholesale (that is the point: the new outline takes the
place of the old one), but the save itself is incremental, so annotations,
form data and page content are untouched.
"""
from __future__ import annotations

from typing import Any

from . import pdf_io

# Reused so an outline always lands in the same file the highlights go to.
from .annot_writer import target_path


def read_toc(paper_id: str) -> list[list[Any]] | None:
    """The PDF's current bookmarks as ``[[level, title, page], ...]`` (1-based
    pages, as PyMuPDF reports them). ``None`` when the file is unusable."""
    with pdf_io.open_path(target_path(paper_id)) as doc:
        if doc is None:
            return None
        try:
            return doc.get_toc(simple=True) or []
        except Exception:
            return []


def write_toc(paper_id: str, entries: list[dict[str, Any]]) -> int:
    """Replace the PDF's bookmarks with ``entries``.

    Entries are Gloss sections (``{title, page, level}``) whose pages are
    0-based; a PDF TOC is 1-based. Returns how many entries were written.
    Raises ``ValueError`` when there is nothing to write or the file refuses.
    """
    if not entries:
        raise ValueError("no outline entries to write")
    path = target_path(paper_id)
    if not path.exists():
        raise ValueError("PDF file not found")
    with pdf_io.lock:
        with pdf_io.open_path(path) as doc:
            if doc is None:
                raise ValueError("PDF could not be opened for writing")
            n_pages = doc.page_count
            toc: list[list[Any]] = []
            for entry in entries:
                title = str(entry.get("title") or "").strip()
                if not title:
                    continue
                try:
                    level = max(1, min(6, int(entry.get("level", 1))))
                except (TypeError, ValueError):
                    level = 1
                try:
                    page = int(entry.get("page", 0)) + 1
                except (TypeError, ValueError):
                    page = 1
                # A stale entry pointing past the last page would make set_toc
                # raise, and the whole write would be lost.
                toc.append([level, title[:200], max(1, min(page, n_pages))])
            if not toc:
                raise ValueError("no usable outline entries to write")
            doc.set_toc(toc)
            pdf_io.save(doc)
    return len(toc)


def clear_toc(paper_id: str) -> None:
    """Remove every bookmark — restoring a PDF that never had any."""
    path = target_path(paper_id)
    if not path.exists():
        raise ValueError("PDF file not found")
    with pdf_io.lock:
        with pdf_io.open_path(path) as doc:
            if doc is None:
                raise ValueError("PDF could not be opened for writing")
            doc.set_toc([])
            pdf_io.save(doc)
