"""Mirror Gloss highlights into the PDF file itself.

Gloss keeps highlights in its own SQLite database, which means they vanish as
soon as the PDF leaves the app. This module writes the same highlights back
into the PDF as **standard, editable PDF highlight annotations** (the kind
Acrobat / Preview / Zotero / Skim all understand), using incremental saves so
existing content, form data and third-party annotations stay untouched.

PyMuPDF uses a top-left origin with the y axis pointing down — exactly the
space the browser (pdf.js) reports selection rectangles in — so the rects
stored in the ``highlights`` table can be handed to PyMuPDF unchanged.

Every annotation Gloss creates is tagged with ``/T = "Gloss"`` so a full
re-sync can safely remove and rebuild only our own markup.
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import fitz  # PyMuPDF

from .. import config
from ..library import store

#: ``/T`` entry written into every annotation we create.
ANNOT_TITLE = "Gloss"

#: #ffd54f — same amber the picker defaults to.
DEFAULT_RGB = (1.0, 0.8353, 0.3098)

# PDFs live on the data disk; two requests touching the same file at once would
# otherwise interleave open + incremental-save and corrupt it.
_lock = threading.RLock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def enabled() -> bool:
    """Whether highlights should be written into the PDF (user setting)."""
    return bool(config.load_config().get("sync_highlights_to_pdf", True))


def target_path(paper_id: str) -> Path:
    """The PDF annotations are written to.

    That is the paper's *original* file (the Zotero / folder copy the user
    actually keeps) when one is linked, and otherwise Gloss's own working copy
    inside the data directory.
    """
    return store.source_pdf_path(paper_id) or store.pdf_path(paper_id)


def target_info(paper_id: str) -> dict[str, Any]:
    """Describe where annotations currently go, for the UI."""
    linked = store.source_pdf_path(paper_id)
    stored = store.linked_source_pdf(paper_id)
    path = linked or store.pdf_path(paper_id)
    return {
        "path": str(path),
        "is_original": linked is not None,
        "exists": path.exists(),
        "linked_path": str(stored) if stored else None,
        # linked but unreachable — the original was moved/renamed/deleted
        "linked_missing": stored is not None and linked is None,
    }


def _parse_color(color: str) -> tuple[float, float, float]:
    value = (color or "").strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        return DEFAULT_RGB
    try:
        return (
            int(value[0:2], 16) / 255,
            int(value[2:4], 16) / 255,
            int(value[4:6], 16) / 255,
        )
    except ValueError:
        return DEFAULT_RGB


def _content(highlight: dict[str, Any]) -> str:
    """Annotation body: the user's note first, then the highlighted passage."""
    note = (highlight.get("note") or "").strip()
    text = (highlight.get("text") or "").strip()
    if note and text:
        return f"{note}\n\n{text}"
    return note or text


def _rects(page: fitz.Page, raw: Any) -> list[fitz.Rect]:
    """Normalize stored rects into page-clipped PyMuPDF rects."""
    bounds = page.rect
    out: list[fitz.Rect] = []
    if not isinstance(raw, (list, tuple)):
        return out
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 4:
            continue
        try:
            rect = fitz.Rect(*(float(v) for v in item))
        except (TypeError, ValueError):
            continue
        rect &= bounds
        if rect.is_empty or rect.width < 0.5 or rect.height < 0.5:
            continue
        out.append(rect)
    return out


def _iter_annots(page: fitz.Page) -> Iterator[fitz.Annot]:
    try:
        annots = list(page.annots())
    except Exception:
        return
    for annot in annots:
        yield annot


def _is_gloss_annot(annot: fitz.Annot) -> bool:
    try:
        return (annot.info.get("title") or "").strip() == ANNOT_TITLE
    except Exception:
        return False


@contextmanager
def _open_pdf(paper_id: str) -> Iterator[fitz.Document | None]:
    """Yield the paper's PDF opened for editing, or ``None`` if unusable."""
    path = target_path(paper_id)
    if not path.exists() or path.stat().st_size == 0:
        yield None
        return
    try:
        doc = fitz.open(str(path))
    except Exception:
        yield None
        return
    try:
        if doc.needs_pass and not doc.authenticate(""):
            yield None
            return
        yield doc
    finally:
        doc.close()


def _save(doc: fitz.Document) -> None:
    """Incremental save (append-only). Falls back to a full rewrite."""
    path = Path(doc.name)
    try:
        doc.saveIncr()
        return
    except Exception:
        pass
    # Some files (heavily repaired / object-stream-only PDFs) refuse an
    # incremental update. Rewrite them once instead of losing the annotation.
    tmp = path.with_name(path.name + ".tmp")
    try:
        doc.save(str(tmp), garbage=0, deflate=True, encryption=fitz.PDF_ENCRYPT_KEEP)
        os.replace(str(tmp), str(path))
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _create(page: fitz.Page, highlight: dict[str, Any]) -> fitz.Annot | None:
    """One native annotation for ``highlight``, honouring its ``style``.

    ``underline`` draws a coloured rule under the text (what auto-highlights use,
    so they stay legible next to the user's own highlights); anything else is a
    classic fill highlight.
    """
    rects = _rects(page, highlight.get("rects"))
    if not rects:
        return None
    style = str(highlight.get("style") or "highlight").lower()
    try:
        if style == "underline":
            annot = page.add_underline_annot(rects)
        elif style == "strikeout":
            annot = page.add_strikeout_annot(rects)
        elif style == "squiggly":
            annot = page.add_squiggly_annot(rects)
        else:
            annot = page.add_highlight_annot(rects)
    except Exception:
        return None
    annot.set_colors(stroke=_parse_color(highlight.get("color", "")))
    annot.set_info(content=_content(highlight), title=ANNOT_TITLE)
    annot.update()
    return annot


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def add(paper_id: str, highlights: list[dict[str, Any]]) -> dict[str, int]:
    """Create one native highlight annotation per highlight.

    Returns ``{highlight_id: pdf_xref}`` for everything that was written, so the
    caller can persist the xref and find the annotation again later.
    """
    if not highlights or not enabled():
        return {}
    written: dict[str, int] = {}
    with _lock, _open_pdf(paper_id) as doc:
        if doc is None:
            return {}
        dirty = False
        for highlight in highlights:
            page_index = int(highlight.get("page") or 0)
            if page_index < 0 or page_index >= doc.page_count:
                continue
            annot = _create(doc.load_page(page_index), highlight)
            if annot is None:
                continue
            written[str(highlight.get("id"))] = annot.xref
            dirty = True
        if dirty:
            _save(doc)
    return written


def ensure(paper_id: str, highlights: list[dict[str, Any]]) -> dict[str, int]:
    """Make the PDF hold exactly one Gloss annotation per highlight.

    Used when a highlight changed (colour / note): the stale annotation is
    dropped and a fresh one written, in a single open + save cycle.
    """
    if not highlights or not enabled():
        return {}
    stale = {int(h["pdf_xref"]) for h in highlights if h.get("pdf_xref")}
    written: dict[str, int] = {}
    with _lock, _open_pdf(paper_id) as doc:
        if doc is None:
            return {}
        dirty = False
        if stale:
            for page_index in range(doc.page_count):
                page = doc.load_page(page_index)
                for annot in _iter_annots(page):
                    if annot.xref in stale:
                        try:
                            page.delete_annot(annot)
                            dirty = True
                        except Exception:
                            pass
        for highlight in highlights:
            page_index = int(highlight.get("page") or 0)
            if page_index < 0 or page_index >= doc.page_count:
                continue
            annot = _create(doc.load_page(page_index), highlight)
            if annot is None:
                continue
            written[str(highlight.get("id"))] = annot.xref
            dirty = True
        if dirty:
            _save(doc)
    return written


def update(paper_id: str, highlights: list[dict[str, Any]]) -> dict[str, int]:
    """Re-colour / re-text annotations already embedded (matched by xref).

    Returns the subset of ``{highlight_id: xref}`` that was actually found;
    anything missing should be re-created by the caller.
    """
    if not highlights or not enabled():
        return {}
    wanted: dict[int, dict[str, Any]] = {}
    for highlight in highlights:
        xref = highlight.get("pdf_xref")
        if xref:
            wanted[int(xref)] = highlight
    if not wanted:
        return {}
    found: dict[str, int] = {}
    with _lock, _open_pdf(paper_id) as doc:
        if doc is None:
            return {}
        dirty = False
        for highlight in highlights:
            page_index = int(highlight.get("page") or 0)
            if page_index < 0 or page_index >= doc.page_count:
                continue
            page = doc.load_page(page_index)
            for annot in _iter_annots(page):
                target = wanted.get(annot.xref)
                if target is None:
                    continue
                try:
                    annot.set_colors(stroke=_parse_color(target.get("color", "")))
                    annot.set_info(content=_content(target), title=ANNOT_TITLE)
                    annot.update()
                except Exception:
                    continue
                found[str(target.get("id"))] = annot.xref
                dirty = True
        if dirty:
            _save(doc)
    return found


def remove(paper_id: str, xrefs: list[int | None]) -> int:
    """Delete the annotations with the given xrefs. Always allowed, so the PDF
    never keeps an annotation whose highlight is already gone."""
    targets = {int(x) for x in xrefs if x}
    if not targets:
        return 0
    removed = 0
    with _lock, _open_pdf(paper_id) as doc:
        if doc is None:
            return 0
        for page_index in range(doc.page_count):
            page = doc.load_page(page_index)
            for annot in _iter_annots(page):
                if annot.xref not in targets:
                    continue
                try:
                    page.delete_annot(annot)
                    removed += 1
                except Exception:
                    pass
        if removed:
            _save(doc)
    return removed


def remove_gloss_annots(paper_id: str) -> int:
    """Delete every annotation tagged ``/T = Gloss`` on every page."""
    removed = 0
    with _lock, _open_pdf(paper_id) as doc:
        if doc is None:
            return 0
        for page_index in range(doc.page_count):
            page = doc.load_page(page_index)
            for annot in _iter_annots(page):
                if not _is_gloss_annot(annot):
                    continue
                try:
                    page.delete_annot(annot)
                    removed += 1
                except Exception:
                    pass
        if removed:
            _save(doc)
    return removed


def count_embedded(paper_id: str) -> int:
    """How many Gloss annotations the PDF currently carries."""
    total = 0
    with _lock, _open_pdf(paper_id) as doc:
        if doc is None:
            return 0
        for page_index in range(doc.page_count):
            total += sum(
                1 for annot in _iter_annots(doc.load_page(page_index))
                if _is_gloss_annot(annot)
            )
    return total


def sync_paper(paper_id: str) -> dict[str, Any]:
    """Full reconcile: rewrite the PDF's Gloss annotations from the database.

    Drops every annotation we own, then re-creates one per stored highlight and
    refreshes the stored xrefs. Repairs PDFs desynced by an older build, by a
    moved data directory, or by annotations edited in another reader.
    """
    highlights = store.list_highlights(paper_id)
    removed = remove_gloss_annots(paper_id)
    written = add(paper_id, highlights) if enabled() else {}
    for highlight in highlights:
        store.set_highlight_xref(
            highlight["id"], written.get(highlight["id"])
        )
    return {
        "written": len(written),
        "removed": removed,
        "total": len(highlights),
        "embedded": count_embedded(paper_id),
    }
