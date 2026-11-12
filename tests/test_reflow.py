"""Reading-mode reflow: two-column order, dropped furniture, joined paragraphs.

The PDFs are synthesised with PyMuPDF, so the layout is known exactly and the
assertions are about the reflow rather than about a particular paper.
"""
from __future__ import annotations

import fitz
import pytest

from backend.app.pdf import reflow

# Two columns on a US Letter page, with a gutter no line crosses.
LEFT_X = 60.0
RIGHT_X = 320.0
COL_W = 230.0
BODY = 11.0
LINE_STEP = 14.0     # inside a paragraph: leading a little wider than the glyph box
PARA_STEP = 26.0     # between paragraphs: enough to read as a break
# Below the header band, so prose is never mistaken for a running header.
FIRST_LINE_Y = 130.0


def _column(page: fitz.Page, x: float, y: float, lines: list[str], step: float = LINE_STEP) -> None:
    for i, text in enumerate(lines):
        page.insert_text((x, y + i * step), text, fontsize=BODY)


def _two_column_pdf() -> bytes:
    doc = fitz.open()
    for pno in range(2):
        page = doc.new_page(width=612, height=792)
        # A running header and a page slug: present on every page, so they are
        # furniture rather than prose.
        page.insert_text((60, 40), "Proceedings of the Test Conference 2026", fontsize=9)
        page.insert_text((60, 760), "Copyright 2026 by the authors", fontsize=9)

        tag = "L" if pno == 0 else "l"
        second = FIRST_LINE_Y + 3 * LINE_STEP + PARA_STEP
        _column(page, LEFT_X, FIRST_LINE_Y, [
            f"{tag}1 alpha", f"{tag}1 beta", f"{tag}1 gamma",
        ])
        _column(page, LEFT_X, second, [
            f"{tag}2 alpha", f"{tag}2 beta",
        ])

        rtag = "R" if pno == 0 else "r"
        _column(page, RIGHT_X, FIRST_LINE_Y, [
            f"{rtag}1 alpha", f"{rtag}1 beta", f"{rtag}1 gamma",
        ])
        _column(page, RIGHT_X, second, [
            f"{rtag}2 alpha", f"{rtag}2 beta",
        ])
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture(scope="module")
def two_column(tmp_path_factory) -> dict:
    path = tmp_path_factory.mktemp("reflow") / "two.pdf"
    path.write_bytes(_two_column_pdf())
    return reflow.build_from_path(path, None)


def _texts(doc: dict) -> list[str]:
    return [b.get("text", "") for b in doc["blocks"]]


def test_detects_two_columns(two_column):
    assert two_column["columns"] == 2
    assert two_column["has_text"]


def test_left_column_is_read_before_right(two_column):
    """The whole point: no left-right zipping across the gutter."""
    texts = _texts(two_column)
    left = [i for i, t in enumerate(texts) if t.startswith("L1")]
    right = [i for i, t in enumerate(texts) if t.startswith("R1")]
    assert left and right
    assert max(left) < min(right), texts


def test_wrapped_lines_join_into_one_paragraph(two_column):
    texts = _texts(two_column)
    joined = [t for t in texts if "L1 alpha" in t]
    assert len(joined) == 1, texts
    assert joined[0] == "L1 alpha L1 beta L1 gamma"


def test_running_header_and_footer_are_dropped(two_column):
    blob = " ".join(_texts(two_column))
    assert "Proceedings of the Test Conference" not in blob
    assert "Copyright 2026" not in blob


def test_full_width_heading_does_not_break_the_columns(tmp_path):
    """A heading spanning the gutter must not be mistaken for a second column.

    This is the case that defeats a naive "two clusters of line positions"
    test: the heading sits over the gutter, so the page's lines look like one
    wide column unless the gutter itself is examined.
    """
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _column(page, LEFT_X, FIRST_LINE_Y, ["2  Method"])
    _column(page, LEFT_X, FIRST_LINE_Y + 30, ["L1 alpha", "L1 beta"])
    _column(page, RIGHT_X, FIRST_LINE_Y + 30, ["R1 alpha", "R1 beta"])
    path = tmp_path / "heading.pdf"
    doc.save(str(path))
    doc.close()

    built = reflow.build_from_path(path, None)
    assert built["columns"] == 1  # a heading alone is not a two-column layout
    texts = _texts(built)
    assert texts[0] == "2  Method"
    left = next(i for i, t in enumerate(texts) if t.startswith("L1"))
    right = next(i for i, t in enumerate(texts) if t.startswith("R1"))
    assert left < right, texts


def test_sentences_carry_pdf_rectangles(two_column):
    """Highlights made in the reading window need somewhere to land."""
    segs = [s for b in two_column["blocks"] for s in b.get("segments", [])]
    assert segs
    assert all(s["sent_id"] for s in segs)
    assert any(s["rects"] for s in segs)
    with_rects = [s for s in segs if s["rects"]]
    # Every rect is a page-coordinate box: x0 < x1, y0 < y1.
    for s in with_rects:
        for x0, y0, x1, y1 in s["rects"]:
            assert x0 < x1 and y0 < y1


def test_single_column_pdf_stays_single(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _column(page, LEFT_X, FIRST_LINE_Y, ["one alpha", "one beta"])
    path = tmp_path / "mono.pdf"
    doc.save(str(path))
    doc.close()

    built = reflow.build_from_path(path, None)
    assert built["columns"] == 1
    assert "one alpha one beta" in " ".join(_texts(built))
