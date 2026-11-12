"""PDF ingestion with PyMuPDF (fitz).

Extracts, per page, text blocks with bounding boxes + dominant font size (used to
anchor highlights/annotations to PDF.js coordinates and to detect section
headers). Produces a ``parsed.json`` document consumed by the reader UI and the
feature endpoints.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz  # PyMuPDF


def ingest_pdf(pdf_path: str | Path) -> dict[str, Any]:
    doc = fitz.open(str(pdf_path))
    pages: list[dict] = []
    full_parts: list[str] = []
    block_uid = 0
    try:
        for pno in range(doc.page_count):
            page = doc.load_page(pno)
            rect = page.rect
            pd = page.get_text("dict")
            blocks = []
            for b in pd.get("blocks", []):
                if b.get("type") != 0:  # 0 = text block; 1 = image
                    continue
                btext_lines = []
                max_size = 0.0
                font = ""
                bold = False
                for line in b.get("lines", []):
                    spans = line.get("spans", [])
                    line_txt = "".join(s.get("text", "") for s in spans)
                    if line_txt.strip():
                        btext_lines.append(line_txt)
                    for s in spans:
                        sz = float(s.get("size", 0))
                        if sz > max_size:
                            max_size = sz
                            font = s.get("font", "")
                        if s.get("flags", 0) & 16:  # bold flag
                            bold = True
                text = "\n".join(btext_lines).strip()
                if not text:
                    continue
                blocks.append({
                    "id": block_uid,
                    "bbox": [round(v, 2) for v in b.get("bbox", [0, 0, 0, 0])],
                    "text": text,
                    "size": round(max_size, 2),
                    "font": font,
                    "bold": bold,
                })
                full_parts.append(text)
                block_uid += 1

            # image/figure rectangles on the page (for figure preview)
            images = []
            for img in page.get_image_info():
                bb = img.get("bbox")
                if bb:
                    images.append([round(v, 2) for v in bb])

            pages.append({
                "index": pno,
                "width": round(rect.width, 2),
                "height": round(rect.height, 2),
                "blocks": blocks,
                "images": images,
            })

        toc = doc.get_toc(simple=True) or []
        meta = doc.metadata or {}
    finally:
        doc.close()

    return {
        "n_pages": len(pages),
        "pages": pages,
        "toc": toc,
        "full_text": "\n\n".join(full_parts),
        "meta": {
            "title": (meta.get("title") or "").strip(),
            "author": (meta.get("author") or "").strip(),
        },
    }


def page_labels(pdf_path: str | Path) -> list[str | None]:
    """The printed page number of each PDF page, where the PDF declares one.

    Journals paginate a paper 1..n while the PDF also holds front matter, so the
    number printed on the page and the position of the page in the file differ.
    ``None`` means the PDF declares no label for that page.
    """
    out: list[str | None] = []
    doc = fitz.open(str(pdf_path))
    try:
        for pno in range(doc.page_count):
            try:
                label = doc.load_page(pno).get_label()
            except Exception:
                label = None
            out.append(label or None)
    finally:
        doc.close()
    return out


#: Fallback probe lengths, tried in order when the whole quote is not found.
#: A shorter head is cut on a word boundary, so it still matches real text
#: rather than ending mid-word where no PDF ever breaks a line.
PROBE_LENGTHS = (80, 40)


def probes(needle: str) -> list[str]:
    """The strings to search a page for, whole quote first.

    A quote is searched whole, because a sentence in a paper wraps over two or
    three rendered lines and only the whole of it spans every line it is on:
    searching a fixed-length head finds the first line and stops there, which
    leaves the highlight covering half a sentence. The shorter heads are a
    fallback for a quote the PDF does not hold as written — hyphenated across a
    line break, or not quite verbatim — where part of it is better than none.
    """
    text = " ".join((needle or "").split())
    if not text:
        return []
    out = [text]
    for length in PROBE_LENGTHS:
        if len(text) <= length:
            continue
        head = text[:length]
        cut = head.rfind(" ")
        if cut > length // 2:
            head = head[:cut]
        if head and head not in out:
            out.append(head)
    return out


def search_page_rects(pdf_path: str | Path, page_index: int, needle: str) -> list[list[float]]:
    """Return bounding rects for ``needle`` on a page (best-effort, for highlights)."""
    needle = " ".join(needle.split())
    if not needle:
        return []
    doc = fitz.open(str(pdf_path))
    try:
        if page_index < 0 or page_index >= doc.page_count:
            return []
        page = doc.load_page(page_index)
        for probe in probes(needle):
            rects = page.search_for(probe, quads=False)
            if rects:
                return [[round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2)] for r in rects]
        return []
    finally:
        doc.close()


def locate_text(pdf_path: str | Path, needle: str, max_pages: int | None = None) -> dict | None:
    """Find the first page containing ``needle`` and return {page, rects}.

    The rectangles cover every rendered line the needle is on, so a quote
    wrapping over three lines highlights all three and not just its first.

    ``exact`` says whether the whole needle was found. When it is false only a
    shortened head matched, so the location is a guess at where the quote is
    rather than the quote itself — worth writing down, but not worth presenting
    as a located quote.
    """
    snippet = " ".join(needle.split())
    if not snippet:
        return None
    doc = fitz.open(str(pdf_path))
    try:
        n = doc.page_count if max_pages is None else min(max_pages, doc.page_count)
        for pno in range(n):
            page = doc.load_page(pno)
            for index, probe in enumerate(probes(snippet)):
                rects = page.search_for(probe, quads=False)
                if rects:
                    return {
                        "page": pno,
                        "rects": [[round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2)] for r in rects],
                        "exact": index == 0,
                    }
    finally:
        doc.close()
    return None
