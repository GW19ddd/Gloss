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

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import fitz  # PyMuPDF

from .. import config
from ..library import store
from . import bilingual, ingest
# Opening, locking and saving a paper's PDF is shared with the outline writer.
from .pdf_io import lock as _lock, open_path as _open_path, save as _save

#: ``/T`` entry written into every annotation we create.
ANNOT_TITLE = "Gloss"
# Note evidence gets its own tag: a highlight re-sync drops and rebuilds
# everything tagged "Gloss" from the database, and evidence annotations are not
# highlights — they must survive that, and stay out of the highlight list.
EVIDENCE_TITLE = "Gloss Evidence"
EVIDENCE_COLOR = "#ffd400"

#: #ffd54f — same amber the picker defaults to.
DEFAULT_RGB = (1.0, 0.8353, 0.3098)


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


def writes_own_copy(paper_id: str) -> bool:
    """Whether annotations land in Gloss's own copy rather than a linked file."""
    try:
        return target_path(paper_id).resolve() == store.pdf_path(paper_id).resolve()
    except OSError:
        return False


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


def paper_pdf_kind(paper_id: str) -> str:
    """What Gloss's own copy of the paper is: 'dual' or 'original'.

    The copy is always called original.pdf, so a bilingual file the reader
    imported cannot be told by its name any more — the two ways left are what
    import recorded (it sees the arriving filename) and looking at the pages. The
    answer is cached in the papers row, so the pages are read at most once.
    """
    stored = store.paper_pdf_kind(paper_id)
    if stored is None:
        stored = bilingual.detect_kind(store.pdf_path(paper_id))
        store.set_paper_pdf_kind(paper_id, stored)
    return stored


def _target_kind(paper_id: str, path: Path) -> str:
    """What path is: 'dual', 'side_by_side', or 'original'.

    A file outside Gloss says it in its name. Gloss's own copy cannot — every
    import is stored as original.pdf — so what import recorded is used there.
    """
    try:
        if Path(path).resolve() == store.pdf_path(paper_id).resolve():
            stored = paper_pdf_kind(paper_id)
            return stored if stored in ("dual", "side_by_side") else "original"
    except OSError:
        pass
    named = bilingual.kind(path)
    return named if named in ("dual", "side_by_side") else "original"


def _mirror_map(paper_id: str, path: Path) -> dict[int, list] | None:
    """Sidecar paragraphs for a bilingual file, or None if path is not one.

    ``{}`` and ``None`` mean different things: a bilingual file without a sidecar
    still mirrors, from the layout; a plain PDF does not mirror at all.
    """
    if _target_kind(paper_id, path) == "original":
        return None
    return bilingual.sidecar_paragraphs(path)


def _partner_page(page_index: int) -> int:
    """The page paired with page_index inside a dual file."""
    return page_index + 1 if page_index % 2 == 0 else page_index - 1


def _page_in_target(
    paper_id: str, target: Path, doc, page_index: int
) -> int | None:
    """Where a highlight belongs inside a bilingual file, or None if not one.

    Two shapes. Gloss's own copy *is* the bilingual file (the reader imported
    it), so the page number the reader drew on already indexes it. Or the
    bilingual file sits outside Gloss beside the source being read, and there a
    dual holds every source page twice over — page p of the source is page 2p of
    it — while a side_by_side keeps one page per source page. Both are confirmed
    by the page count first; anything unconfirmed is left alone rather than
    mirrored onto the wrong page.
    """
    kind_ = _target_kind(paper_id, target)
    if kind_ == "original":
        return None
    own = store.pdf_path(paper_id)
    try:
        if Path(target).resolve() == own.resolve():
            return page_index
        if not own.exists():
            return None
        with _open_path(own) as source:
            if source is None:
                return None
            if kind_ == "side_by_side" and doc.page_count == source.page_count:
                return page_index
            if kind_ == "dual" and doc.page_count == 2 * source.page_count:
                return page_index * 2
    except OSError:
        return None
    return None


def _partner_annots(
    doc,
    mirror: dict[int, list] | None,
    page_index: int,
    content: str,
    kind_: str = "dual",
    skip_xref: int | None = None,
) -> list[tuple[fitz.Page, fitz.Annot]]:
    """(page, annot) of the mirrors of an annotation, found by its content.

    A side_by_side mirror sits on the very page of the original, so the page is
    searched too and the annotation being handled is skipped.

    The page is handed back with the annotation because PyMuPDF only accepts a
    deletion from the very page object the annotation belongs to.
    """
    if mirror is None or not content:
        return []
    # A dual pairs pages; a side_by_side pairs columns of one page.
    others = [page_index] if kind_ == "side_by_side" else [_partner_page(page_index)]
    out: list[tuple[fitz.Page, fitz.Annot]] = []
    for other in others:
        if not 0 <= other < doc.page_count:
            continue
        page = doc.load_page(other)
        for annot in _iter_annots(page):
            if skip_xref is not None and annot.xref == skip_xref:
                continue
            try:
                if not _is_gloss_annot(annot):
                    continue
                if (annot.info.get("content") or "").strip() == content:
                    out.append((page, annot))
            except Exception:
                continue
    return out


@contextmanager
def _open_pdf(paper_id: str) -> Iterator[fitz.Document | None]:
    """Yield the paper's PDF opened for editing, or ``None`` if unusable."""
    with _open_path(target_path(paper_id)) as doc:
        yield doc


def _create(
    page: fitz.Page, highlight: dict[str, Any], title: str = ANNOT_TITLE
) -> fitz.Annot | None:
    """One native annotation for ``highlight``, honouring its ``style``.

    ``underline`` draws a coloured rule under the text (what auto-highlights use,
    so they stay legible next to the user's own highlights); anything else is a
    classic fill highlight. ``title`` becomes the PDF ``/T`` entry — evidence
    annotations pass their own so a highlight re-sync never touches them.
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
    annot.set_info(content=_content(highlight), title=title)
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
    target = target_path(paper_id)
    written: dict[str, int] = {}
    with _lock, _open_path(target) as doc:
        if doc is None:
            return {}
        kind_ = _target_kind(paper_id, target)
        mirror = _mirror_map(paper_id, target)
        dirty = False
        for highlight in highlights:
            page_index = int(highlight.get("page") or 0)
            if page_index < 0 or page_index >= doc.page_count:
                continue
            paired = (
                _page_in_target(paper_id, target, doc, page_index)
                if mirror is not None
                else None
            )
            if paired is not None:
                page_index = paired
            annot = _create(doc.load_page(page_index), highlight)
            if annot is None:
                continue
            written[str(highlight.get("id"))] = annot.xref
            dirty = True
            if paired is not None:
                _create_mirror(doc, mirror, page_index, highlight, kind_)
        if dirty:
            _save(doc)
    return written


def _create_mirror(
    doc, mirror: dict[int, list], page_index: int, item: dict, kind_: str = "dual"
) -> None:
    """Put the same mark on the translation paired with page_index.

    A dual pairs pages, so the copy goes on the page facing it; a side_by_side
    pairs columns, so the copy goes beside it on the very page.
    """
    if kind_ == "side_by_side":
        rects = bilingual.side_by_side_rects(
            doc, page_index, item.get("rects"), mirror.get(page_index),
            str(item.get("quote") or ""),
        )
        if not rects:
            return
        try:
            _create(doc.load_page(page_index), {**item, "rects": rects})
        except Exception:
            pass
        return
    rects = bilingual.mirror_rects(
        doc, page_index, item.get("rects"), mirror.get(page_index // 2)
    )
    if not rects:
        return
    try:
        _create(doc.load_page(page_index + 1), {**item, "rects": rects})
    except Exception:
        pass


def ensure(paper_id: str, highlights: list[dict[str, Any]]) -> dict[str, int]:
    """Make the PDF hold exactly one Gloss annotation per highlight.

    Used when a highlight changed (colour / note): the stale annotation is
    dropped and a fresh one written, in a single open + save cycle.
    """
    if not highlights or not enabled():
        return {}
    stale = {int(h["pdf_xref"]) for h in highlights if h.get("pdf_xref")}
    target = target_path(paper_id)
    written: dict[str, int] = {}
    with _lock, _open_path(target) as doc:
        if doc is None:
            return {}
        kind_ = _target_kind(paper_id, target)
        mirror = _mirror_map(paper_id, target)
        dirty = False
        if stale:
            for page_index in range(doc.page_count):
                page = doc.load_page(page_index)
                for annot in _iter_annots(page):
                    if annot.xref in stale:
                        _delete_mirrors(doc, mirror, page_index, annot)
                        try:
                            page.delete_annot(annot)
                            dirty = True
                        except Exception:
                            pass
        for highlight in highlights:
            page_index = int(highlight.get("page") or 0)
            if page_index < 0 or page_index >= doc.page_count:
                continue
            paired = (
                _page_in_target(paper_id, target, doc, page_index)
                if mirror is not None
                else None
            )
            if paired is not None:
                page_index = paired
            annot = _create(doc.load_page(page_index), highlight)
            if annot is None:
                continue
            written[str(highlight.get("id"))] = annot.xref
            dirty = True
            if paired is not None:
                _create_mirror(doc, mirror, page_index, highlight, kind_)
        if dirty:
            _save(doc)
    return written


def _delete_mirrors(
    doc,
    mirror: dict[int, list] | None,
    page_index: int,
    annot,
    kind_: str = "dual",
) -> int:
    """Drop the copies this annotation has on the translation paired with it."""
    try:
        content = (annot.info.get("content") or "").strip()
    except Exception:
        return 0
    removed = 0
    for page, partner in _partner_annots(
        doc, mirror, page_index, content, kind_, skip_xref=annot.xref
    ):
        try:
            page.delete_annot(partner)
            removed += 1
        except Exception:
            continue
    return removed


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
        kind_ = _target_kind(paper_id, target_path(paper_id))
        mirror = _mirror_map(paper_id, target_path(paper_id))
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
                    before = (annot.info.get("content") or "").strip()
                except Exception:
                    before = ""
                try:
                    annot.set_colors(stroke=_parse_color(target.get("color", "")))
                    annot.set_info(content=_content(target), title=ANNOT_TITLE)
                    annot.update()
                except Exception:
                    continue
                found[str(target.get("id"))] = annot.xref
                dirty = True
                # The mirror carries the old text, so it is matched before the
                # edit and then brought to the same text.
                for _, partner in _partner_annots(
                    doc, mirror, page_index, before, kind_, skip_xref=annot.xref
                ):
                    try:
                        partner.set_colors(
                            stroke=_parse_color(target.get("color", ""))
                        )
                        partner.set_info(content=_content(target), title=ANNOT_TITLE)
                        partner.update()
                    except Exception:
                        continue
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
        kind_ = _target_kind(paper_id, target_path(paper_id))
        mirror = _mirror_map(paper_id, target_path(paper_id))
        for page_index in range(doc.page_count):
            page = doc.load_page(page_index)
            for annot in _iter_annots(page):
                if annot.xref not in targets:
                    continue
                removed += _delete_mirrors(doc, mirror, page_index, annot, kind_)
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


# ---------------------------------------------------------------------------
# Note evidence -> native annotations
# ---------------------------------------------------------------------------
def _locate_in_page(
    doc: fitz.Document, page_index: int, quote: str
) -> tuple[list[list[float]], bool]:
    """Re-find ``quote`` on one page; its rects and whether the whole was found.

    Evidence is located against Gloss's own copy of the PDF; when the write
    target is a different file (the linked original) the stored geometry may not
    line up, so search the target instead of trusting the rects blindly.

    One rectangle per rendered line: a sentence in a paper wraps, and a mark
    covering only its first line would leave the reader looking at half a quote
    and believing that is what the note was about.

    ``False`` comes back when only a shortened head of the quote matched — the
    note is not verbatim, or the PDF hyphenates it. A mark is still written,
    because part of a sentence beats none, but it is reported as approximate:
    a reader has to be able to tell a located quote from a guessed one.
    """
    try:
        page = doc.load_page(page_index)
    except Exception:
        return [], False
    for index, probe in enumerate(ingest.probes(quote)):
        try:
            rects = page.search_for(probe, quads=False)
        except Exception:
            return [], False
        if rects:
            return (
                [
                    [round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2)]
                    for r in rects
                ],
                index == 0,
            )
    return [], False


def _evidence_seen(doc: fitz.Document) -> list[tuple[int, str]]:
    """(page, content) of every evidence annotation already in ``doc``."""
    seen: list[tuple[int, str]] = []
    for page_index in range(doc.page_count):
        for annot in _iter_annots(doc.load_page(page_index)):
            try:
                info = annot.info or {}
                if (info.get("title") or "").strip() != EVIDENCE_TITLE:
                    continue
                seen.append((page_index, (info.get("content") or "").strip()))
            except Exception:
                continue
    return seen


def _zone_key(page_index: int, rects: list) -> tuple:
    """Identity of the spot an annotation covers.

    Evidence is a pair — one English passage, one translation of it — and both
    halves of a pair can resolve onto the same paragraph of a translated page.
    They share a key here, so only the first is written instead of two
    highlights stacking on top of each other.
    """
    box: fitz.Rect | None = None
    for r in rects:
        if not isinstance(r, (list, tuple)) or len(r) != 4:
            continue
        try:
            part = fitz.Rect(*(float(v) for v in r))
        except (TypeError, ValueError):
            continue
        box = part if box is None else box | part
    if box is None:
        return (page_index,)
    return (
        page_index,
        round(box.x0, 1),
        round(box.y0, 1),
        round(box.x1, 1),
        round(box.y1, 1),
    )


def _evidence_zones(doc) -> set[tuple]:
    """Spots a evidence annotation in ``doc`` already covers."""
    zones: set[tuple] = set()
    for page_index in range(doc.page_count):
        for annot in _iter_annots(doc.load_page(page_index)):
            try:
                info = annot.info or {}
                if (info.get("title") or "").strip() != EVIDENCE_TITLE:
                    continue
                zones.add(_zone_key(page_index, [annot.rect]))
            except Exception:
                continue
    return zones


def _evidence_annot(doc, page_index: int, rects: list, item: dict):
    return _create(
        doc.load_page(page_index),
        {
            "rects": rects,
            "text": str(item.get("quote") or ""),
            "note": str(item.get("why") or ""),
            "color": EVIDENCE_COLOR,
            "style": "highlight",
        },
        title=EVIDENCE_TITLE,
    )


def _union_box(rects: list) -> fitz.Rect | None:
    """The one box covering every rectangle of a mark."""
    box: fitz.Rect | None = None
    for r in rects:
        if not isinstance(r, (list, tuple)) or len(r) != 4:
            continue
        try:
            part = fitz.Rect(*(float(v) for v in r))
        except (TypeError, ValueError):
            continue
        box = part if box is None else box | part
    return box


def _same_spot(a: fitz.Rect, b: fitz.Rect | None) -> bool:
    """True when two boxes cover the same lines.

    Overlap over union, not equality: a highlight read back is never the box it
    was given, PyMuPDF padding it out by about half a line, while one left on
    the wrong lines overlaps the right ones hardly at all.
    """
    if b is None or a.is_empty or b.is_empty:
        return False
    return (a & b).get_area() / (a | b).get_area() >= 0.5


def _mirror_annots(
    doc, partner_page: int, probe: str, mark: fitz.Rect | None
) -> list[tuple[fitz.Page, fitz.Annot]]:
    """(page, annot) of the evidence marks on a translation, minus the mark itself.

    A side_by_side mirror shares its page with the English mark and says the
    same thing as it, so the two are told apart by where they sit: the mark is
    the box it was written on, the mirror is anything else saying the same.
    """
    if not probe or not 0 <= partner_page < doc.page_count:
        return []
    page = doc.load_page(partner_page)
    out: list[tuple[fitz.Page, fitz.Annot]] = []
    for annot in _iter_annots(page):
        try:
            info = annot.info or {}
            if (info.get("title") or "").strip() != EVIDENCE_TITLE:
                continue
            if probe not in (info.get("content") or ""):
                continue
        except Exception:
            continue
        if _same_spot(fitz.Rect(annot.rect), mark):
            continue
        out.append((page, annot))
    return out


def add_evidence(
    paper_id: str,
    evidence: list[dict[str, Any]],
    *,
    path: str | Path | None = None,
    mirror: bool = False,
) -> list[dict[str, Any]]:
    """Write note evidence into the PDF as real highlight annotations.

    Every reader (Acrobat, Preview, WPS, and Zotero, which imports them as
    annotations on open) shows them, so the evidence follows the file instead of
    living only inside Gloss. Already-written evidence is skipped, so re-running
    the export does not pile up duplicates — and a mirror left on the wrong
    lines by an earlier version is moved onto the right ones rather than left
    be, so re-running the export repairs an export made before that was known.

    ``path`` overrides the destination, so evidence can also land on a PaperFlow
    translation; the caller is responsible for mapping pages and rectangles onto
    that file first.

    ``mirror`` additionally puts each mark on the translated page paired with it,
    which is what makes a bilingual file show the same evidence on both sides of
    the spread.
    """
    results: list[dict[str, Any]] = []
    if not evidence or not enabled():
        return results
    target = Path(path) if path else target_path(paper_id)
    kind_ = _target_kind(paper_id, target)
    mirror_map = _mirror_map(paper_id, target) if mirror else None
    with _lock, _open_path(target) as doc:
        if doc is None:
            return results
        seen = _evidence_seen(doc)
        zones = _evidence_zones(doc)
        dirty = False
        for item in evidence:
            eid = item.get("id")
            try:
                page_index = int(item.get("page"))
            except (TypeError, ValueError):
                results.append({"id": eid, "xref": None, "error": "no page"})
                continue
            if not 0 <= page_index < doc.page_count:
                results.append({"id": eid, "xref": None, "error": "page out of range"})
                continue
            quote = str(item.get("quote") or "")
            rects = item.get("rects") or []
            approximate = False
            if not rects:
                rects, approximate = _locate_in_page(doc, page_index, quote)
            if not rects:
                results.append({"id": eid, "xref": None, "error": "not found in pdf"})
                continue
            def _mirror_result(page_index: int, rects: list, item: dict, eid, probe: str):
                """Put the mark on the translation paired with it, and keep it there.

                What it covers is compared against what is already on the page,
                not merely whether something is: a mirror written by an older
                Gloss covers the paragraph where the sentence was, so leaving it
                be would keep the mistake however many times the export ran. One
                already on the right lines is left alone.
                """
                if mirror_map is None:
                    return None
                if kind_ == "side_by_side":
                    paired = bilingual.side_by_side_rects(
                        doc, page_index, rects, mirror_map.get(page_index),
                        str(item.get("quote") or ""),
                    )
                    partner_page = page_index  # the column beside it, same page
                else:
                    paired = bilingual.mirror_rects(
                        doc, page_index, rects, mirror_map.get(page_index // 2),
                        str(item.get("quote") or ""),
                    )
                    partner_page = page_index + 1
                if not paired:
                    return None
                want = _union_box(paired)
                if want is None:
                    return None
                stale: list[tuple[fitz.Page, fitz.Annot]] = []
                for page, annot in _mirror_annots(
                    doc, partner_page, probe, _union_box(rects)
                ):
                    if _same_spot(fitz.Rect(annot.rect), want):
                        return None  # already on the lines it belongs on
                    stale.append((page, annot))
                for page, annot in stale:
                    try:
                        page.delete_annot(annot)
                    except Exception:
                        continue
                mirror_key = _zone_key(partner_page, paired)
                if mirror_key in zones and not stale:
                    return None
                partner = _evidence_annot(doc, partner_page, paired, item)
                if partner is None:
                    return None
                zones.add(mirror_key)
                moved = {"moved": True} if stale else {}
                return {
                    "id": eid,
                    "xref": partner.xref,
                    "page": partner_page,
                    "mirror": True,
                    **moved,
                }

            # The whole quote, normalised: two notes sharing their first eighty
            # characters are not the same note, and skipping the second would
            # drop a piece of evidence the reader asked for. Comparing against
            # the normalised mark lets spacing differ without a duplicate.
            probe = " ".join(quote.split())
            key = _zone_key(page_index, rects)
            already = any(
                p == page_index
                and probe
                and probe in " ".join(content.split())
                for p, content in seen
            )
            if already or key in zones:
                # The mark is there already; the translation beside it may not
                # be, from an export made before Gloss mirrored at all.
                late = _mirror_result(page_index, rects, item, eid, probe)
                if late is None:
                    results.append({"id": eid, "xref": None, "skipped": True})
                    continue
                dirty = True
                results.append(late)
                continue
            annot = _evidence_annot(doc, page_index, rects, item)
            if annot is None:
                results.append({"id": eid, "xref": None, "error": "create failed"})
                continue
            zones.add(key)
            seen.append((page_index, f"{item.get('why') or ''}\n\n{quote}"))
            dirty = True
            results.append(
                {
                    "id": eid,
                    "xref": annot.xref,
                    "page": page_index,
                    **({"approximate": True} if approximate else {}),
                }
            )
            if mirror_map is None:
                continue
            mirrored = _mirror_result(page_index, rects, item, eid, probe)
            if mirrored:
                dirty = True
                results.append(mirrored)
        if dirty:
            _save(doc)
    return results


def remove_evidence(paper_id: str, *, path: str | Path | None = None) -> int:
    """Delete every evidence annotation from the PDF.

    ``path`` overrides which file is cleared, so evidence written onto a
    translation can be removed from that same file rather than from the source.
    """
    removed = 0
    target = Path(path) if path else target_path(paper_id)
    with _lock, _open_path(target) as doc:
        if doc is None:
            return 0
        for page_index in range(doc.page_count):
            page = doc.load_page(page_index)
            for annot in _iter_annots(page):
                try:
                    if (annot.info.get("title") or "").strip() != EVIDENCE_TITLE:
                        continue
                    page.delete_annot(annot)
                    removed += 1
                except Exception:
                    continue
        if removed:
            _save(doc)
    return removed


def count_evidence(paper_id: str, *, path: str | Path | None = None) -> int:
    """How many evidence annotations the PDF currently carries.

    ``path`` overrides which file is counted, so a translation reports its own
    annotations instead of the source's.
    """
    total = 0
    target = Path(path) if path else target_path(paper_id)
    with _lock, _open_path(target) as doc:
        if doc is None:
            return 0
        for page_index in range(doc.page_count):
            for annot in _iter_annots(doc.load_page(page_index)):
                try:
                    if (annot.info.get("title") or "").strip() == EVIDENCE_TITLE:
                        total += 1
                except Exception:
                    continue
    return total
