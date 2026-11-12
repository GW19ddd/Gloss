"""Reflow a paper's PDF into one continuous reading column.

A two-column conference paper is typeset for print: on screen it means a small
font, a reading order that zips left-right, and wasted margins. Reading mode
rebuilds the pages as a single column — the way Acrobat's Reading Mode and the
Zotero reflow plugins do it — so the text reads like a document and can be
enlarged freely.

Two things shape the design:

* The output is **structured, not HTML**. The front end renders it as React
  elements, which keeps text escaped for free and lets the translation swap
  happen per sentence instead of per blob of markup.
* Every sentence keeps **the PDF rectangles it occupies**. That is the same
  shape Zotero's reader stores for a highlight — page coordinates, one rect per
  rendered line — so a highlight made in the reading window is written straight
  into the PDF with the code that already exists, and a highlight made in the
  PDF can be shown back in the reading window.
"""
from __future__ import annotations

import json
import shutil
import statistics
from pathlib import Path
from typing import Any

import fitz

from ..features.translate import _sid, get_translations
from ..library import store
from ..pdf import annot_writer, bilingual, ingest, pdf_io, structure

# A repeated line in these bands of the page is furniture, not prose.
_HEAD_ZONE = 0.14
_FOOT_ZONE = 0.12
# How often a line must recur across the paper before it counts as a running
# header: at least twice, so a short two-page note still loses its slug, and a
# share of the paper, so a long one loses page numbers without a stray repeated
# line of prose being taken for furniture.
_BOILERPLATE_MIN_PAGES = 2
_BOILERPLATE_MIN_SHARE = 0.4
_BOILERPLATE_MAX_LEN = 80

# Column split: only a gap in the middle band of the space being laid out
# separates two columns — the band is a share of that space, so it works for a
# whole page and for one half of a bilingual spread alike.
_GAP_LO = 0.35
_GAP_HI = 0.65
_GAP_STEP = 2.0
_GAP_MAX_CROSSING_SHARE = 0.1
_GAP_MIN_SIDE_SHARE = 0.25

# Paragraph building.
_LINE_GAP_FACTOR = 0.9          # vertical gap below this fraction of a line height keeps a paragraph
_SIZE_TOLERANCE = 0.7           # pt; two lines this far apart in size are different things
_INDENT_TOLERANCE = 2.5         # pt; a first line this much further right starts a paragraph
_HEADING_SIZE_FACTOR = 1.1      # over the paper's body size
_HEADING_MAX_LEN = 160

_SENT_GROUP_FACTOR = 3.0        # rects further apart than this many line heights are a second occurrence

_FIG_MIN = 60.0                 # pt; ignore logos and bullet glyphs
_FIG_TEXT_OVERLAP = 0.5         # an image most of which is covered by text is a background, not a figure
_FIG_DPI = 144


def _norm(text: str) -> str:
    return " ".join((text or "").split())


def reading_path(paper_id: str) -> Path:
    return store.paper_dir(paper_id) / "reading.json"


def figure_dir(paper_id: str) -> Path:
    return store.paper_dir(paper_id) / "reading"


def figure_file(paper_id: str, name: str) -> Path | None:
    """Resolve a figure name from the reading document to a file on disk.

    Names are validated against the directory: a request must not be able to
    walk out of the paper's own folder.
    """
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    p = figure_dir(paper_id) / name
    return p if p.is_file() else None


# --------------------------------------------------------------------------
# page geometry
# --------------------------------------------------------------------------

def _rows(page: fitz.Page, clip: fitz.Rect | None = None) -> list[dict]:
    """Rendered text lines of a page, each with its box and font size.

    ``clip`` restricts this to part of the page — a side-by-side bilingual
    spread holds two papers' worth of text, and only the original half is
    prose to be read. Boxes stay in whole-page coordinates either way, because
    that is the space highlights live in.
    """
    out: list[dict] = []
    data = page.get_text("dict", clip=clip)
    for b in data.get("blocks", []):
        if b.get("type") != 0:  # 0 = text, 1 = image
            continue
        for line in b.get("lines", []):
            spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            text = "".join(s.get("text", "") for s in spans).strip()
            if not text:
                continue
            bb = line.get("bbox") or spans[0].get("bbox") or (0, 0, 0, 0)
            out.append({
                "text": text,
                "size": max(float(s.get("size", 0)) for s in spans),
                "x0": float(bb[0]), "y0": float(bb[1]),
                "x1": float(bb[2]), "y1": float(bb[3]),
            })
    return out


def _boilerplate(doc_rows: list[list[dict]], heights: list[float]) -> set[str]:
    """Lines that repeat across the paper in the header/footer bands.

    These are page numbers, running titles and copyright slugs. Left in, they
    drop into the prose every page and read as noise; the test is recurrence
    rather than position because position alone would also catch the first
    line of every column.
    """
    seen: dict[str, set[int]] = {}
    for pno, rows in enumerate(doc_rows):
        h = heights[pno]
        for r in rows:
            top = r["y0"] < h * _HEAD_ZONE
            bottom = r["y1"] > h * (1 - _FOOT_ZONE)
            if not (top or bottom):
                continue
            # Compared verbatim, not case-folded: a running header is identical
            # every time, and folding would also fold two different column-opening
            # lines into one another.
            key = _norm(r["text"])
            if not key or len(key) > _BOILERPLATE_MAX_LEN:
                continue
            seen.setdefault(key, set()).add(pno)
    if not seen:
        return set()
    n = len(doc_rows)
    threshold = max(_BOILERPLATE_MIN_PAGES, int(n * _BOILERPLATE_MIN_SHARE))
    return {k for k, pages in seen.items() if len(pages) >= threshold}


def _column_gap(rows: list[dict], lo: float, hi: float) -> float | None:
    """The x in [lo, hi] that splits the page into two columns, or ``None``.

    Scanning for an uncrossed gutter rather than clustering line centres keeps
    a full-width title from faking a second column: a title spans the gutter,
    so no x near the middle is ever free of it on a single-column page.
    """
    if len(rows) < 8 or hi <= lo:
        return None
    middle = (lo + hi) / 2
    best: float | None = None
    x = lo
    while x <= hi:
        crossing = sum(1 for r in rows if r["x0"] < x < r["x1"])
        if crossing <= len(rows) * _GAP_MAX_CROSSING_SHARE:
            left = sum(1 for r in rows if r["x1"] <= x)
            right = sum(1 for r in rows if r["x0"] >= x)
            if left >= len(rows) * _GAP_MIN_SIDE_SHARE and right >= len(rows) * _GAP_MIN_SIDE_SHARE:
                if best is None or abs(x - middle) < abs(best - middle):
                    best = x
        x += _GAP_STEP
    return best


def _ordered(rows: list[dict], gap: float | None) -> list[dict]:
    """Reading order: left column top to bottom, then the right one.

    Rows are bucketed by y before sorting because the two columns are typeset
    independently and their baselines never line up exactly; sorting on raw y
    would interleave them.
    """
    def col_of(r: dict) -> int:
        return 0 if gap is None else (1 if (r["x0"] + r["x1"]) / 2 >= gap else 0)

    for r in rows:
        # Carried on the row: a paragraph must not run across the gutter, and
        # knowing which column each line was in is the only way to tell.
        r["col"] = col_of(r)

    def key(r: dict) -> tuple:
        return (r["col"], round(r["y0"] / 3.0), round(r["x0"] / 6.0))

    return sorted(rows, key=key)


def _join(rows: list[dict]) -> str:
    """Line texts into one paragraph, undoing hyphenation at line breaks.

    ``inter-\nnational`` is one word broken for the measure, not two: joining
    with a space would leave a stray hyphen in the middle of the prose. The
    lowercase test keeps a real hyphenated compound (``state-of-``) intact.
    """
    text = ""
    for r in rows:
        t = r["text"].strip()
        if not text:
            text = t
        elif text.endswith("-") and t[:1].islower():
            text = text[:-1] + t
        else:
            text += " " + t
    return text.strip()


def _paragraphs(rows: list[dict]) -> list[dict]:
    """Group reading-ordered rows into paragraphs."""
    out: list[dict] = []
    cur: list[dict] = []
    for r in rows:
        if not cur:
            cur = [r]
            continue
        prev = cur[-1]
        height = max(prev["y1"] - prev["y0"], 1.0)
        gap = r["y0"] - prev["y1"]
        same_size = abs(r["size"] - prev["size"]) <= _SIZE_TOLERANCE
        # Moving to the other column — or jumping back up the page — ends the
        # paragraph, whatever the numbers say. Typesetters do sometimes set a
        # leading tighter than the glyph box, so a slightly negative gap is
        # still the next line rather than a jump.
        moved = r.get("col") != prev.get("col") or gap < -height * 0.5
        close = (not moved) and gap < height * _LINE_GAP_FACTOR
        hyphenated = prev["text"].endswith("-") and (not moved) and gap < height * 2
        # A first line sitting further right than the one above is a new
        # paragraph even when the vertical gap is small.
        indented = r["x0"] > cur[0]["x0"] + _INDENT_TOLERANCE and gap > height * 0.2
        if (hyphenated or (close and not indented)) and same_size:
            cur.append(r)
        else:
            out.append(cur)
            cur = [r]
    if cur:
        out.append(cur)
    return [{"rows": g} for g in out]


def _sentence_rects(page: fitz.Page, text: str, line_height: float) -> list[list[float]]:
    """Rects a sentence occupies on the page — one per rendered line.

    Asking the PDF to find its own text beats mapping character offsets by
    hand: a sentence wrapped over three lines yields three rects, and a
    sentence broken by a column change yields rects in both columns. When the
    sentence is not found verbatim (hyphenated, or the extractor dropped a
    glyph) the shorter probes used elsewhere in the app get a partial answer
    rather than none.
    """
    rects = page.search_for(text, quads=False)
    if not rects:
        for probe in ingest.probes(text)[1:]:
            rects = page.search_for(probe, quads=False)
            if rects:
                break
    if not rects:
        return []
    rects = sorted(rects, key=lambda r: (round(r.y0, 1), r.x0))
    group = [rects[0]]
    for r in rects[1:]:
        # A jump of more than a few lines means the sentence occurs again
        # further down; that is a second match, not a continuation of this one.
        if r.y0 - group[-1].y0 > line_height * _SENT_GROUP_FACTOR:
            break
        group.append(r)
    return [[round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2)] for r in group]


def _overlap_area(box: tuple, row: dict) -> float:
    ox = max(0.0, min(box[2], row["x1"]) - max(box[0], row["x0"]))
    oy = max(0.0, min(box[3], row["y1"]) - max(box[1], row["y0"]))
    return ox * oy


def _figures(page: fitz.Page, rows: list[dict], out_dir: Path, pno: int, clip: fitz.Rect | None = None) -> list[dict]:
    """Crop the page's real figures so they survive the reflow.

    A figure is an image big enough to be content that is not mostly covered by
    text — that second test is what separates a plotted figure from a
    full-bleed background or a watermark.
    """
    out: list[dict] = []
    for i, img in enumerate(page.get_image_info()):
        bb = img.get("bbox")
        if not bb:
            continue
        box = (float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3]))
        w, h = box[2] - box[0], box[3] - box[1]
        if w < _FIG_MIN or h < _FIG_MIN:
            continue
        if clip is not None and not (clip.x0 <= (box[0] + box[2]) / 2 <= clip.x1):
            continue  # it belongs to the other half of the spread
        covered = sum(_overlap_area(box, r) for r in rows) / max(w * h, 1.0)
        if covered > _FIG_TEXT_OVERLAP:
            continue
        name = f"p{pno}-{i}.png"
        try:
            pix = page.get_pixmap(clip=fitz.Rect(*box), dpi=_FIG_DPI)
            if pix.width < 8 or pix.height < 8:
                continue
            pix.save(str(out_dir / name))
        except Exception:
            continue
        out.append({
            "type": "figure", "page": pno, "bbox": [round(v, 2) for v in box],
            "text": "", "segments": [], "image": name,
            "_sort_col": box[0], "_y": box[1],
        })
    return out


# --------------------------------------------------------------------------
# document build
# --------------------------------------------------------------------------

# Bump when the shape of the reflowed document changes, so a cache written by
# an older version is rebuilt instead of being served with missing fields.
_CACHE_VERSION = 2


def _source_signature(path: Path) -> str:
    st = path.stat()
    return f"v{_CACHE_VERSION}|{path}|{int(st.st_mtime)}|{st.st_size}"


def build_reading_doc(paper_id: str, *, force: bool = False) -> dict:
    """Reflow the paper's PDF into a single-column reading document.

    Cached next to the paper: the layout analysis walks every line of every
    page and asks the PDF to locate every sentence, which is far too slow to
    repeat on each open. The cache is keyed on the source file's identity, so
    re-linking the paper to a different PDF rebuilds it.
    """
    cache_file = reading_path(paper_id)
    path = annot_writer.target_path(paper_id)
    if not path.exists() or path.stat().st_size == 0:
        return {"blocks": [], "n_pages": 0, "columns": 1, "has_text": False, "source": ""}

    sig = _source_signature(path)
    if not force and cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if cached.get("source") == sig:
                return cached
        except Exception:
            pass

    doc = build_from_path(path, paper_id)
    doc["source"] = sig
    try:
        cache_file.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return doc


def build_from_path(pdf_path: Path, paper_id: str | None = None) -> dict:
    """The reflow itself, run against a concrete file (also used by tests)."""
    out_dir = figure_dir(paper_id) if paper_id else None
    if out_dir:
        # Figures are named by page and index; clearing first stops crops from
        # a previous layout (or a shorter previous PDF) from being served.
        shutil.rmtree(out_dir, ignore_errors=True)
        out_dir.mkdir(parents=True, exist_ok=True)

    with pdf_io.open_path(Path(pdf_path)) as doc:
        if doc is None:
            return {"blocks": [], "n_pages": 0, "columns": 1, "has_text": False}

        # A bilingual PDF is not one paper but two: a side-by-side spread puts
        # the original beside its translation on every page, and an interleaved
        # one alternates original and translated pages. Reading both would
        # double the prose — and the translation is available on demand anyway —
        # so the reflow keeps only the original half.
        kind = bilingual.detect_kind(pdf_path)

        doc_rows: list[list[dict]] = []
        heights: list[float] = []
        clips: list[fitz.Rect | None] = []
        for pno in range(doc.page_count):
            page = doc.load_page(pno)
            if kind == "dual" and pno % 2 == 1:
                continue  # a translated page, not prose to read
            clip = None
            if kind == "side_by_side":
                shift = bilingual.side_by_side_shift(page)
                if shift:
                    width = float(page.rect.width)
                    # shift is positive when the translation sits to the right.
                    clip = (
                        fitz.Rect(0, 0, width / 2, page.rect.height)
                        if shift > 0
                        else fitz.Rect(width / 2, 0, width, page.rect.height)
                    )
            doc_rows.append(_rows(page, clip))
            heights.append(float(page.rect.height))
            clips.append(clip)

        junk = _boilerplate(doc_rows, heights)
        all_sizes = [r["size"] for rows in doc_rows for r in rows]
        body_size = statistics.median(all_sizes) if all_sizes else 10.0

        blocks: list[dict] = []
        double = 0
        source_pages: list[int] = []
        for index, rows in enumerate(doc_rows):
            page = doc.load_page(index)
            clip = clips[index]
            pno = page.number
            source_pages.append(pno)
            rows = [r for r in rows if _norm(r["text"]) not in junk]
            if not rows:
                continue
            span_lo = clip.x0 if clip is not None else 0.0
            span_hi = clip.x1 if clip is not None else float(page.rect.width)
            gap = _column_gap(
                rows, span_lo + (span_hi - span_lo) * _GAP_LO, span_lo + (span_hi - span_lo) * _GAP_HI
            )
            if gap is not None:
                double += 1

            def column(x: float) -> int:
                return 0 if gap is None else (1 if x >= gap else 0)

            ordered = _ordered(rows, gap)
            line_height = statistics.median(
                [r["y1"] - r["y0"] for r in ordered]
            ) if ordered else 12.0

            for para in _paragraphs(ordered):
                prows = para["rows"]
                text = _join(prows)
                if len(_norm(text)) < 2:
                    continue
                size = max(r["size"] for r in prows)
                is_heading = size > body_size * _HEADING_SIZE_FACTOR and len(text) < _HEADING_MAX_LEN
                segments = []
                for sent in structure.split_sentences(text):
                    segments.append({
                        "text": sent,
                        "sent_id": _sid(sent),
                        "rects": _sentence_rects(page, sent, line_height),
                    })
                blocks.append({
                    "type": "heading" if is_heading else "p",
                    "page": pno,
                    "bbox": [
                        round(min(r["x0"] for r in prows), 2), round(min(r["y0"] for r in prows), 2),
                        round(max(r["x1"] for r in prows), 2), round(max(r["y1"] for r in prows), 2),
                    ],
                    "text": text,
                    "segments": segments,
                    "image": None,
                    # Judged by its left edge, not its centre: a paragraph that
                    # straddles the gutter — a figure caption, a section head —
                    # has its centre on the gutter and would otherwise be filed
                    # under the right column however far left it starts.
                    "_col": column(min(r["x0"] for r in prows)),
                    "_y": min(r["y0"] for r in prows),
                })

            if out_dir is not None:
                for fig in _figures(page, rows, out_dir, pno, clip):
                    fig["_col"] = column(fig.pop("_sort_col"))
                    blocks.append(fig)

        n_pages = len(doc_rows)

    blocks.sort(key=lambda b: (b["page"], b.get("_col", 0), b.get("_y", 0.0)))
    for b in blocks:
        b.pop("_col", None)
        b.pop("_y", None)

    return {
        "blocks": blocks,
        # Pages that carry prose. A bilingual PDF's translated pages are not
        # among them, which is what "translate the whole paper" then costs.
        "n_pages": n_pages,
        "source_pages": source_pages,
        # Two columns only when most pages are laid out that way: a single
        # two-column figure page or a wide table page should not decide it.
        "columns": 2 if n_pages and double >= max(2, int(n_pages * 0.5)) else 1,
        "has_text": bool(blocks),
    }


def attach_translations(doc: dict, paper_id: str, language: str | None = None) -> dict:
    """Add ``translations`` — sentence id to translated text — to a reading doc.

    The translation cache is keyed by a hash of the sentence as the PDF parser
    split it, and a reflowed paragraph can join lines the parser kept apart, so
    a hash alone misses sentences the paper has actually had translated. Exact
    text is tried as well, which recovers those.
    """
    try:
        done = get_translations(paper_id, language=language)
    except Exception:
        return {**doc, "translations": {}}

    by_id = {_sid(t["original"]): t["translation"] for t in done if t.get("translation")}
    by_text = {_norm(t["original"]): t["translation"] for t in done if t.get("translation")}

    out: dict[str, str] = {}
    for b in doc.get("blocks", []):
        for seg in b.get("segments", []):
            t = by_id.get(seg["sent_id"]) or by_text.get(_norm(seg["text"]))
            if t:
                out[seg["sent_id"]] = t
    return {**doc, "translations": out}
