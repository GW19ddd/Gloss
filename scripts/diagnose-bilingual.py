"""Why is a bilingual paper not being mirrored?

Run this against a real paper to see every step of the decision:

    python scripts/diagnose-bilingual.py --title "attention"
    python scripts/diagnose-bilingual.py --id 6f1c...
    python scripts/diagnose-bilingual.py --file path/to/paper.pdf

It prints what Gloss decided and why, so a report like "the Chinese side gets
nothing" can be traced to the step that actually failed.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

try:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows console
except Exception:
    pass

from app import config  # noqa: E402
from app.library import store  # noqa: E402
from app.pdf import annot_writer, bilingual  # noqa: E402

CJK_FONT_HINTS = [
    "cjk", "noto", "sourcehan", "source_han", "simsun", "nsimsun", "stsong",
    "stxihei", "stkaiti", "stfangsong", "songti", "simhei", "msyh", "yahei",
    "wqy", "gothic", "mincho", "meiryo", "malgun", "droidsansfallback",
]

SAMPLE = 8  # pages reported from the front of the file


def _font_names(page) -> list[str]:
    try:
        fonts = page.get_fonts()
    except Exception:
        return []
    names = []
    for font in fonts:
        base = str(font[3] or "")
        if base and base not in names:
            names.append(base)
    return names


def _cjk_fonts(page) -> list[str]:
    names = _font_names(page)
    return [
        name for name in names
        if any(hint in name.lower() for hint in CJK_FONT_HINTS)
    ]


def _page_report(doc, index: int) -> str:
    page = doc.load_page(index)
    try:
        text = page.get_text() or ""
    except Exception:
        text = ""
    share = bilingual._cjk_share(text)
    fonts = _cjk_fonts(page)
    return (
        f"  page {index:>3}: {len(text):>6} chars  "
        f"cjk={share:>5.2f}  "
        f"fonts={fonts or '-'}"
    )


def _find_paper(title: str) -> tuple[str, str] | None:
    if not store.DB_PATH.exists():
        return None
    con = sqlite3.connect(store.DB_PATH)
    try:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT id, title, pdf_kind FROM papers ORDER BY added_at DESC"
        ).fetchall()
    finally:
        con.close()
    needle = title.lower()
    for row in rows:
        if needle in (row["title"] or "").lower():
            return row["id"], row["title"]
    return None


def _paper_kind(paper_id: str) -> str:
    con = sqlite3.connect(store.DB_PATH)
    try:
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT pdf_kind FROM papers WHERE id=?", (paper_id,)
        ).fetchone()
    finally:
        con.close()
    return (row["pdf_kind"] if row and row["pdf_kind"] else "(empty)")


def _probe(doc, mirror, kind_: str) -> None:
    """Try mirroring a band of each original page and report the outcome."""
    print(f"\nmirror probe ({kind_}):")
    for index in range(0, min(doc.page_count, 2 * SAMPLE), 2):
        page = doc.load_page(index)
        middle = (page.rect.x0 + page.rect.x1) / 2
        top = float(page.rect.y0 + page.rect.height * 0.45)
        band = [
            float(page.rect.x0 + 20),
            top,
            (middle if kind_ == "side_by_side" else float(page.rect.x1)) - 20,
            top + 20,
        ]
        if kind_ == "side_by_side":
            print(f"  shift: {bilingual.side_by_side_shift(page)}")
            rects = bilingual.side_by_side_rects(
                doc, index, [band], mirror.get(index)
            )
        else:
            rects = bilingual.mirror_rects(
                doc, index, [band], mirror.get(index // 2)
            )
        print(f"  page {index} -> {len(rects)} rect(s) {rects[:2]}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", help="paper id")
    parser.add_argument("--title", help="paper title (substring, case-insensitive)")
    parser.add_argument("--file", help="a PDF to inspect without the library")
    args = parser.parse_args()

    print(f"data dir: {config.DATA_DIR}")
    print(f"database: {store.DB_PATH} ({'found' if store.DB_PATH.exists() else 'MISSING'})")

    path: Path
    paper_id = ""
    if args.file:
        path = Path(args.file)
        print(f"\nfile: {path}")
    else:
        if args.id:
            paper_id, title = args.id, "(by id)"
        elif args.title:
            found = _find_paper(args.title)
            if not found:
                print("\nno paper matches that title")
                return 1
            paper_id, title = found
        else:
            parser.error("give --id, --title or --file")
            return 2
        print(f"\npaper: {title}\nid:    {paper_id}")
        print(f"pdf_kind stored: {_paper_kind(paper_id)}")
        path = annot_writer.target_path(paper_id)
        print(f"annotations go to: {path}")
        print(f"is Gloss's own copy: {annot_writer.writes_own_copy(paper_id)}")
        try:
            print(f"judged bilingual: {annot_writer._target_kind(paper_id, path)}")
            print(f"   (lazy kind: {annot_writer.paper_pdf_kind(paper_id)})")
        except Exception as exc:
            print(f"judged bilingual: ERROR {exc}")

    if not path.exists():
        print(f"\nfile missing: {path}")
        return 1

    import fitz

    doc = fitz.open(str(path))
    try:
        print(f"\npages: {doc.page_count} ({'even' if doc.page_count % 2 == 0 else 'ODD'})")
        print(f"detect_kind: {bilingual.detect_kind(str(path))}")
        print("\npage contents (first pages):")
        for index in range(min(doc.page_count, 2 * SAMPLE)):
            print(_page_report(doc, index))

        gloss = []
        for index in range(doc.page_count):
            page = doc.load_page(index)
            try:
                for annot in page.annots():
                    title = (annot.info.get("title") or "").strip()
                    if title.startswith("Gloss"):
                        gloss.append((index, title, (annot.info.get("content") or "")[:40]))
            except Exception:
                continue
        print(f"\nexisting Gloss annotations: {len(gloss)}")
        for index, title, content in gloss:
            print(f"  page {index:>3} [{title}] {content!r}")

        detected = bilingual.detect_kind(str(path))
        _probe(doc, bilingual.sidecar_paragraphs(path), detected)
    finally:
        doc.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
