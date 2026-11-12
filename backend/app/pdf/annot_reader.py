"""Read the annotations already living inside a paper's PDF.

Gloss draws its own highlights from its database, so what sits inside the file
was never read back: evidence marks written for a note, and anything Zotero or
another reader put there, stayed invisible inside Gloss even though every other
reader showed them. This module reads them back so Gloss can draw them and so a
reader can delete one in place.

Two files can hold them: the copy Gloss renders (always read — its page numbers
are the ones on screen) and, when one is linked, the original the writer targets.
The original is only read when it holds the same number of pages: a bilingual
file numbers its pages differently, and drawing those numbers on the copy would
put every mark on the wrong page.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..library import store
from .annot_writer import (
    ANNOT_TITLE,
    EVIDENCE_TITLE,
    _iter_annots,
    _lock,
    _open_path,
    _save,
    target_path,
)

#: Which file an annotation was read from.
COPY = "copy"
ORIGINAL = "original"

#: What a read-back annotation is, judged from its ``/T`` entry.
GLOSS = "gloss"
GLOSS_EVIDENCE = "gloss_evidence"
EXTERNAL = "external"

#: Annotation subtypes that mark text and so can be drawn as boxes. Ink curves
#: and pop-ups carry no geometry Gloss can redraw, and links are not markup.
MARKUP_SUBTYPES = frozenset({"Highlight", "Underline", "Squiggly", "Strikeout"})


def _files(paper_id: str) -> list[tuple[str, Path]]:
    """The files to read, Gloss's copy first and the linked original second."""
    files = [(COPY, store.pdf_path(paper_id))]
    original = target_path(paper_id)
    try:
        if original.resolve() != store.pdf_path(paper_id).resolve():
            files.append((ORIGINAL, original))
    except OSError:
        pass
    return files


def _kind(title: str) -> str:
    if title == EVIDENCE_TITLE:
        return GLOSS_EVIDENCE
    if title == ANNOT_TITLE:
        return GLOSS
    return EXTERNAL


def _hex(color: Any) -> str | None:
    """An annotation's stroke colour as ``#rrggbb``, or None when it has none."""
    if not color:
        return None
    try:
        red, green, blue = (max(0.0, min(1.0, float(value))) for value in color)
    except (TypeError, ValueError):
        return None
    return "#{:02x}{:02x}{:02x}".format(
        round(red * 255), round(green * 255), round(blue * 255)
    )


def _stroke(annot: Any) -> str | None:
    """The colour the annotation is drawn in, if it carries one."""
    try:
        colors = annot.colors or {}
    except Exception:
        return None
    return _hex(colors.get("stroke") or colors.get("fill"))


def _boxes(annot: Any) -> list[list[float]]:
    """Boxes a markup annotation covers — one per quad, so a highlight spanning
    three lines is three boxes rather than one slab over the space between."""
    flat: list[float] = []
    try:
        points = annot.vertices
    except Exception:
        points = None
    for point in points or []:
        if isinstance(point, (int, float)):
            flat.append(float(point))
        elif isinstance(point, (list, tuple)) and len(point) == 2:
            flat.append(float(point[0]))
            flat.append(float(point[1]))
    boxes: list[list[float]] = []
    if len(flat) >= 8:
        for start in range(0, len(flat) - 7, 8):
            xs = flat[start:start + 8:2]
            ys = flat[start + 1:start + 8:2]
            boxes.append(
                [round(min(xs), 2), round(min(ys), 2), round(max(xs), 2), round(max(ys), 2)]
            )
    if boxes:
        return boxes
    try:
        rect = annot.rect
    except Exception:
        return []
    return [[round(rect.x0, 2), round(rect.y0, 2), round(rect.x1, 2), round(rect.y1, 2)]]


def _read(doc: Any, source: str, out: list[dict[str, Any]]) -> None:
    for page_index in range(doc.page_count):
        for annot in _iter_annots(doc.load_page(page_index)):
            try:
                subtype = annot.type[1] if len(annot.type) > 1 else ""
            except Exception:
                continue
            if subtype not in MARKUP_SUBTYPES:
                continue
            boxes = _boxes(annot)
            if not boxes:
                continue
            try:
                info = annot.info or {}
            except Exception:
                info = {}
            title = (info.get("title") or "").strip()
            out.append(
                {
                    "xref": int(annot.xref),
                    "page": page_index,
                    "rects": boxes,
                    "color": _stroke(annot),
                    "content": str(info.get("content") or ""),
                    "title": title,
                    "author": str(info.get("name") or info.get("author") or ""),
                    "type": subtype,
                    "source": source,
                    "kind": _kind(title),
                }
            )


def list_annotations(paper_id: str) -> list[dict[str, Any]]:
    """Every text-markup annotation inside the paper's PDF, evidence and
    third-party marks included, in reading order."""
    out: list[dict[str, Any]] = []
    with _lock:
        copy_path = store.pdf_path(paper_id)
        page_count = 0
        with _open_path(copy_path) as doc:
            if doc is None:
                return []
            page_count = doc.page_count
            _read(doc, COPY, out)
        for source, path in _files(paper_id)[1:]:
            with _open_path(path) as doc:
                if doc is None or doc.page_count != page_count:
                    continue
                _read(doc, source, out)
    out.sort(
        key=lambda item: (item["page"], item["rects"][0][1], item["rects"][0][0])
    )
    return out


def remove_annotations(
    paper_id: str, xrefs: list[int], source: str = COPY
) -> int:
    """Delete the annotations with these xrefs from the file they came from."""
    wanted = {int(xref) for xref in xrefs if xref}
    if not wanted:
        return 0
    path = (
        target_path(paper_id) if source == ORIGINAL else store.pdf_path(paper_id)
    )
    removed = 0
    with _lock, _open_path(path) as doc:
        if doc is None:
            return 0
        for page_index in range(doc.page_count):
            page = doc.load_page(page_index)
            for annot in _iter_annots(page):
                if annot.xref not in wanted:
                    continue
                try:
                    page.delete_annot(annot)
                    removed += 1
                except Exception:
                    pass
        if removed:
            _save(doc)
    return removed
