"""Evidence mapped from the source PDF onto a PaperFlow translation.

Dual files interleave original and translated pages, so page ``p`` becomes
``2p`` (original, rectangles carry over) and ``2p+1`` (translated, re-typeset).
Nothing here runs pdf2zh: the PDFs are built with PyMuPDF.
"""
from __future__ import annotations

import json

import fitz
import pytest

from app.pdf import bilingual

SOURCE_LINE = "We propose the Transformer, based solely on attention."
TRANS_LINES = ["TRANSLATED LINE ONE", "TRANSLATED LINE TWO", "TRANSLATED LINE THREE"]
CJK_LINE = "我们提出了 Transformer，一种仅基于注意力机制的模型。"
SIZE = (595.0, 842.0)


def _doc(pages: int, size=SIZE, lines=()) -> fitz.Document:
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page(width=size[0], height=size[1])
        for j, line in enumerate(lines):
            page.insert_text((72.0, 100.0 + 12.0 * j), line, fontsize=11)
    return doc


def _save(doc: fitz.Document, path) -> fitz.Document:
    doc.save(str(path))
    doc.close()
    return doc


def _dual(path, pages: int, size=SIZE) -> None:
    """A dual PDF: original page, translated page, original page, ..."""
    src = _doc(pages, size, [SOURCE_LINE])
    # Three tightly spaced lines stand in for one paragraph that pdf2zh split.
    trans = _doc(pages, size, TRANS_LINES)
    out = fitz.open()
    for i in range(pages):
        out.insert_pdf(src, from_page=i, to_page=i)
        out.insert_pdf(trans, from_page=i, to_page=i)
    _save(out, path)
    src.close()
    trans.close()


def _cjk_dual(path, pages: int) -> None:
    """A dual PDF whose facing pages are genuinely Chinese."""
    src = _doc(pages, SIZE, [SOURCE_LINE])
    out = fitz.open()
    for i in range(pages):
        out.insert_pdf(src, from_page=i, to_page=i)
        page = out.new_page(width=SIZE[0], height=SIZE[1])
        page.insert_text((72.0, 100.0), CJK_LINE, fontname="china-s", fontsize=11)
    _save(out, path)
    src.close()


def _side_by_side(path, pages: int) -> None:
    """A side_by_side PDF: the original page beside its translated one."""
    src = _doc(pages, SIZE, [SOURCE_LINE])
    trans = fitz.open()
    for _ in range(pages):
        page = trans.new_page(width=SIZE[0], height=SIZE[1])
        for offset, line in enumerate((CJK_LINE, CJK_LINE)):
            page.insert_text(
                (72.0, 100.0 + offset * 20), line, fontname="china-s", fontsize=11
            )
    out = fitz.open()
    for i in range(pages):
        page = out.new_page(width=SIZE[0] * 2, height=SIZE[1])
        page.show_pdf_page(fitz.Rect(0, 0, SIZE[0], SIZE[1]), src, i)
        page.show_pdf_page(fitz.Rect(SIZE[0], 0, SIZE[0] * 2, SIZE[1]), trans, i)
    _save(out, path)
    src.close()
    trans.close()


def test_kind_and_sibling_paths(tmp_path):
    src = tmp_path / "paper.pdf"
    _save(_doc(1, SIZE, [SOURCE_LINE]), src)
    (tmp_path / "paper-dual.pdf").write_bytes(b"x")
    (tmp_path / "paper-map.json").write_text("{}")

    assert bilingual.kind(src) == "original"
    assert bilingual.kind(tmp_path / "paper-dual.pdf") == "dual"
    assert bilingual.kind(tmp_path / "paper-mono.pdf") == "mono"
    assert bilingual.kind(tmp_path / "paper-side_by_side.pdf") == "side_by_side"
    assert bilingual.dual_path_for(src) == tmp_path / "paper-dual.pdf"
    assert bilingual.sidecar_path_for(src) == tmp_path / "paper-map.json"
    # Asking a dual file for its dual resolves back to itself.
    assert bilingual.dual_path_for(tmp_path / "paper-dual.pdf") == (
        tmp_path / "paper-dual.pdf"
    )


def test_original_pages_reuse_rectangles(tmp_path):
    src = tmp_path / "paper.pdf"
    _save(_doc(2, SIZE, [SOURCE_LINE]), src)
    dual = tmp_path / "paper-dual.pdf"
    _dual(dual, 2)
    evidence = [{
        "id": "E1", "quote": SOURCE_LINE, "why": "核心主张", "page": 1,
        "rects": [[72.0, 90.0, 300.0, 105.0]],
    }]

    out = bilingual.map_evidence(dual, evidence, source_path=src)

    # Page 1 of the source is page 2 of the dual, and the box is unchanged.
    assert out[0]["page"] == 2
    assert out[0]["rects"] == [[72.0, 90.0, 300.0, 105.0]]


def test_original_pages_relocate_when_sizes_differ(tmp_path):
    src = tmp_path / "paper.pdf"
    _save(_doc(2, (400.0, 600.0), [SOURCE_LINE]), src)
    dual = tmp_path / "paper-dual.pdf"
    _dual(dual, 2, (595.0, 842.0))  # different size: rectangles can't carry over
    evidence = [{
        "id": "E1", "quote": SOURCE_LINE, "why": "核心主张", "page": 0,
        "rects": [[72.0, 90.0, 300.0, 105.0]],
    }]

    out = bilingual.map_evidence(dual, evidence, source_path=src)

    # Falls back to finding the quote by text, on an original (even) page.
    assert out[0]["rects"] != [[72.0, 90.0, 300.0, 105.0]]
    assert out[0]["rects"], "the quote should have been found again"
    assert out[0]["page"] % 2 == 0


def _covered(rects) -> tuple[float, float]:
    ys = [r[1] for r in rects] + [r[3] for r in rects]
    return min(ys), max(ys)


def test_translated_page_covers_the_whole_paragraph(tmp_path):
    """One source paragraph, re-typeset as three lines, is covered as one unit."""
    mono = tmp_path / "paper-mono.pdf"
    _save(_doc(1, SIZE, TRANS_LINES), mono)
    evidence = [{
        "id": "E1", "quote": SOURCE_LINE, "why": "核心主张", "page": 0,
        "rects": [[72.0, 88.0, 300.0, 132.0]],
    }]

    out = bilingual.map_evidence_to_translated(mono, evidence, source_path=mono)

    top, bottom = _covered(out[0]["rects"])
    # PyMuPDF may report the three lines as one block or three; either way the
    # highlight has to span the whole paragraph, not just its first line.
    assert top < 100.0
    assert bottom > 120.0


def test_sidecar_beats_clustering(tmp_path):
    mono = tmp_path / "paper-mono.pdf"
    _save(_doc(1, SIZE, TRANS_LINES), mono)
    # The map sits next to the *source* name, so it is paper-map.json.
    (tmp_path / "paper-map.json").write_text(
        json.dumps({
            "version": 1,
            "coord": "fitz",
            "pages": [{
                "page": 0, "width": SIZE[0], "height": SIZE[1],
                "paragraphs": [{
                    "orig": [72.0, 88.0, 300.0, 132.0],
                    "trans": [[50.0, 50.0, 90.0, 60.0], [50.0, 62.0, 90.0, 72.0]],
                }],
            }],
        }),
        encoding="utf-8",
    )
    evidence = [{
        "id": "E1", "quote": SOURCE_LINE, "why": "核心主张", "page": 0,
        "rects": [[72.0, 88.0, 300.0, 132.0]],
    }]

    out = bilingual.map_evidence_to_translated(mono, evidence, source_path=mono)

    assert out[0]["rects"] == [[50.0, 50.0, 90.0, 60.0], [50.0, 62.0, 90.0, 72.0]]


def test_no_paragraph_hit_falls_back_to_the_projected_box(tmp_path):
    mono = tmp_path / "paper-mono.pdf"
    _save(_doc(1, SIZE, TRANS_LINES), mono)
    evidence = [{
        "id": "E1", "quote": SOURCE_LINE, "why": "核心主张", "page": 0,
        "rects": [[72.0, 600.0, 300.0, 620.0]],  # nowhere near the text
    }]

    out = bilingual.map_evidence_to_translated(mono, evidence, source_path=mono)

    assert len(out[0]["rects"]) == 1
    # The projected box is padded a little, to allow for reflow.
    assert out[0]["rects"][0][1] == pytest.approx(594.0, abs=1.0)


def _slivers(rows: int, per_row: int = 20) -> list[list[float]]:
    """What PaperFlow emits for one paragraph: a rectangle per text object.

    Formula characters are objects of their own, so a paragraph easily runs to
    dozens of slivers. Lines are left slightly overlapping, as measured on real
    output, so merging must not collapse two lines into one.
    """
    out = []
    for i in range(rows):
        top = 100.0 + 15.0 * i  # 16pt tall boxes on a 15pt pitch: 1pt overlap
        for j in range(per_row):
            x0 = 72.0 + 10.0 * j
            out.append([x0, top, x0 + 10.0, top + 16.0])
    return out


def _write_map(tmp_path, trans, orig=(72.0, 88.0, 300.0, 132.0)) -> None:
    (tmp_path / "paper-map.json").write_text(
        json.dumps({
            "version": 1,
            "coord": "fitz",
            "pages": [{
                "page": 0, "width": SIZE[0], "height": SIZE[1],
                "paragraphs": [{"orig": list(orig), "trans": trans}],
            }],
        }),
        encoding="utf-8",
    )


def test_sidecar_is_found_under_a_temporary_name(tmp_path):
    """PaperFlow names the map after the file it was handed, not the source."""
    src = tmp_path / "paper.pdf"
    _save(_doc(1, SIZE, [SOURCE_LINE]), src)
    other = tmp_path / "tmp9f3k-map.json"  # a PDF downloaded from a URL
    other.write_text('{"coord": "fitz"}')

    assert bilingual.sidecar_path_for(src) == other


def test_a_folder_sharing_several_maps_is_not_guessed(tmp_path):
    src = tmp_path / "paper.pdf"
    _save(_doc(1, SIZE, [SOURCE_LINE]), src)
    (tmp_path / "a-map.json").write_text("{}")
    (tmp_path / "b-map.json").write_text("{}")

    assert bilingual.sidecar_path_for(src) is None


def test_sidecar_slivers_merge_back_into_lines(tmp_path):
    mono = tmp_path / "paper-mono.pdf"
    _save(_doc(1, SIZE, TRANS_LINES), mono)
    _write_map(tmp_path, _slivers(3))
    evidence = [{
        "id": "E1", "quote": SOURCE_LINE, "why": "核心主张", "page": 0,
        "rects": [[72.0, 88.0, 300.0, 132.0]],
    }]

    out = bilingual.map_evidence_to_translated(mono, evidence, source_path=mono)

    assert len(out[0]["rects"]) == 3  # 60 slivers, three lines
    first = out[0]["rects"][0]
    assert first[0] == pytest.approx(72.0)
    assert first[2] == pytest.approx(272.0)  # the whole line, not one sliver


def test_a_phrase_still_finds_its_paragraph(tmp_path):
    """Evidence is often a phrase, not a whole paragraph."""
    mono = tmp_path / "paper-mono.pdf"
    _save(_doc(1, SIZE, TRANS_LINES), mono)
    _write_map(tmp_path, _slivers(2))
    evidence = [{
        "id": "E1", "quote": SOURCE_LINE, "why": "核心主张", "page": 0,
        "rects": [[80.0, 90.0, 180.0, 102.0]],  # a phrase inside the paragraph
    }]

    out = bilingual.map_evidence_to_translated(mono, evidence, source_path=mono)

    assert len(out[0]["rects"]) == 2


def test_rectangles_stay_on_the_page(tmp_path):
    """A line PaperFlow could not wrap runs past the edge; the highlight may not."""
    mono = tmp_path / "paper-mono.pdf"
    _save(_doc(1, SIZE, TRANS_LINES), mono)
    _write_map(tmp_path, [[72.0, 100.0, 900.0, 116.0]])
    evidence = [{
        "id": "E1", "quote": SOURCE_LINE, "why": "核心主张", "page": 0,
        "rects": [[72.0, 88.0, 300.0, 132.0]],
    }]

    out = bilingual.map_evidence_to_translated(mono, evidence, source_path=mono)

    assert out[0]["rects"][0][2] == pytest.approx(SIZE[0])


def test_detect_kind_recognises_a_dual_file_without_its_name(tmp_path):
    """Gloss renames every import, so the pages are the only evidence left."""
    path = tmp_path / "renamed-by-import.pdf"
    _cjk_dual(path, 2)

    assert bilingual.detect_kind(path) == "dual"


def test_detect_kind_leaves_a_plain_pdf_alone(tmp_path):
    path = tmp_path / "paper.pdf"
    _save(_doc(2, SIZE, [SOURCE_LINE]), path)

    assert bilingual.detect_kind(path) == "original"


def test_detect_kind_leaves_a_translated_only_pdf_alone(tmp_path):
    """Every page is a translation: it is a mono file, not a dual one."""
    path = tmp_path / "paper.pdf"
    doc = fitz.open()
    for _ in range(2):
        page = doc.new_page(width=SIZE[0], height=SIZE[1])
        page.insert_text((72.0, 100.0), CJK_LINE, fontname="china-s", fontsize=11)
    _save(doc, path)

    assert bilingual.detect_kind(path) == "original"


def test_side_by_side_maps_onto_the_translated_column(tmp_path):
    """Both columns live on one page, so the page stays and the box crosses."""
    path = tmp_path / "paper-side_by_side.pdf"
    _side_by_side(path, 1)
    evidence = [{
        "id": "E1", "quote": SOURCE_LINE, "why": "核心主张", "page": 0,
        "rects": [[72.0, 88.0, 300.0, 104.0]],
    }]

    out = bilingual.map_evidence_to_translated(path, evidence)

    assert out[0]["page"] == 0
    assert out[0]["rects"], out
    assert out[0]["rects"][0][0] >= SIZE[0]  # on the translated column


def test_detect_kind_recognises_a_side_by_side_file_without_its_name(tmp_path):
    path = tmp_path / "renamed-by-import.pdf"
    _side_by_side(path, 2)

    assert bilingual.detect_kind(path) == "side_by_side"


EN_COLUMN = [
    "Figure 1 shows the overall pipeline.",
    "It achieved 83.0% coverage on 183 real modules.",
    "The results show it beats the baselines.",
]
ZH_COLUMN = [
    "图 1 展示了整体流程。",
    "我们提出了一个新的框架用于测试生成。",
    "该方法在 183 个真实模块上达到了 83.0% 的覆盖率。",
    "实验结果表明该方法优于基线方法。",
]


def _spread(path, english, chinese) -> None:
    """A side_by_side page: one column of English beside one of Chinese."""
    src = fitz.open()
    page = src.new_page(width=SIZE[0], height=SIZE[1])
    for i, line in enumerate(english):
        page.insert_text((72.0, 100.0 + 20.0 * i), line, fontsize=11)
    trans = fitz.open()
    page = trans.new_page(width=SIZE[0], height=SIZE[1])
    for i, line in enumerate(chinese):
        page.insert_text(
            (72.0, 100.0 + 20.0 * i), line, fontname="china-s", fontsize=11
        )
    out = fitz.open()
    page = out.new_page(width=SIZE[0] * 2, height=SIZE[1])
    page.show_pdf_page(fitz.Rect(0, 0, SIZE[0], SIZE[1]), src, 0)
    page.show_pdf_page(fitz.Rect(SIZE[0], 0, SIZE[0] * 2, SIZE[1]), trans, 0)
    out.save(str(path))
    for doc in (out, src, trans):
        doc.close()


def test_a_quote_finds_its_own_sentence_by_its_numbers(tmp_path):
    """The sentence the height points at is not always the sentence it became.

    The two columns are typeset apart, so a translated sentence can sit a line
    or two from where the original's suggests. What a translation carries over
    untouched — here 183 and 83.0% — says which sentence it is.
    """
    path = tmp_path / "paper-side_by_side.pdf"
    _spread(path, EN_COLUMN, ZH_COLUMN)
    evidence = [{
        "id": "E1", "quote": EN_COLUMN[1], "why": "结果", "page": 0,
        "rects": [[72.0, 108.0, 400.0, 126.0]],  # the second English line
    }]

    out = bilingual.map_evidence_to_translated(path, evidence)

    assert out[0]["rects"], out
    assert out[0]["rects"][0][0] >= SIZE[0]  # on the translated column
    doc = fitz.open(str(path))
    try:
        page = doc.load_page(0)
        got = "".join(
            page.get_text("text", clip=fitz.Rect(*r)) for r in out[0]["rects"]
        )
    finally:
        doc.close()
    assert "183" in got, got
    assert "83.0%" in got, got
    # One sentence, not the paragraph it sits in.
    assert "整体流程" not in got, got
    assert "优于基线" not in got, got
