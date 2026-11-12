"""Note evidence written back into the PDF as native annotations.

Evidence annotations are tagged ``/T = "Gloss Evidence"`` rather than ``Gloss``:
a highlight re-sync drops and rebuilds everything tagged ``Gloss``, and evidence
annotations must survive that while staying out of the highlight list.
"""
from __future__ import annotations

from pathlib import Path

import fitz
from app.library import store
from pdf_helpers import annot_facts, make_highlight, served_pdf

EVIDENCE = [
    {
        "id": "E1",
        "quote": "We propose the Transformer, a model based solely on attention mechanisms.",
        "why": "核心主张",
        "page": 0,
        "rects": [],  # no geometry: it has to be found by text
    },
    {
        "id": "E2",
        "quote": "[1] Vaswani et al. Attention is all you need. NeurIPS 2017.",
        "why": "出处",
        "page": 1,
        "rects": [[72.0, 90.0, 400.0, 110.0]],
    },
]


def _write(client, paper_id: str, evidence=None, target="auto", side="original"):
    resp = client.post(
        f"/api/papers/{paper_id}/evidence/pdf",
        json={
            "evidence": EVIDENCE if evidence is None else evidence,
            "target": target,
            "side": side,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _dual_path(paper_id: str) -> Path:
    """Where PaperFlow would leave the dual file beside Gloss's copy."""
    return store.pdf_path(paper_id).with_name("original-dual.pdf")


def _write_dual(paper_id: str, pdf_bytes: bytes) -> Path:
    """A stand-in dual PDF: each source page followed by a translated page.

    The "translation" repeats the source sentences, so evidence that carries no
    geometry can still be located on the translated page.
    """
    src = fitz.open(stream=pdf_bytes, filetype="pdf")
    trans = fitz.open()
    for _ in range(src.page_count):
        page = trans.new_page(width=612, height=792)
        page.insert_text((72, 72), EVIDENCE[0]["quote"], fontsize=11)
        page.insert_text((72, 100), EVIDENCE[1]["quote"], fontsize=11)
    dual = fitz.open()
    for i in range(src.page_count):
        dual.insert_pdf(src, from_page=i, to_page=i)
        dual.insert_pdf(trans, from_page=i, to_page=i)
    data = dual.tobytes()
    for doc in (src, trans, dual):
        doc.close()
    path = _dual_path(paper_id)
    path.write_bytes(data)
    return path


def _evidence_facts(data: bytes) -> list[dict]:
    return [f for f in annot_facts(data) if f["title"] == "Gloss Evidence"]


# --- a bilingual paper imported straight into Gloss --------------------------
# Gloss stores every import as original.pdf, so the -dual name is gone and being
# bilingual has to be read off the pages: even pages English, odd pages Chinese.
_TRANSLATIONS = [
    "我们提出了 Transformer，一种仅基于注意力机制的模型。",
    "参考文献：Vaswani 等人，Attention is all you need，NeurIPS 2017。",
]

# Evidence located in that file: its pages are dual pages, so the source page 1
# is page 2 here.
DUAL_EVIDENCE = [
    {**EVIDENCE[0], "page": 0},
    {**EVIDENCE[1], "page": 2},
]


def _cjk_dual_bytes(pdf_bytes: bytes) -> bytes:
    """The sample paper as a dual file, with genuinely Chinese facing pages."""
    src = fitz.open(stream=pdf_bytes, filetype="pdf")
    dual = fitz.open()
    for index in range(src.page_count):
        dual.insert_pdf(src, from_page=index, to_page=index)
        page = dual.new_page(width=612, height=792)
        for offset, line in enumerate(_TRANSLATIONS):
            page.insert_text(
                (72, 72 + offset * 28), line, fontname="china-s", fontsize=11
            )
    data = dual.tobytes()
    for doc in (src, dual):
        doc.close()
    return data


def _side_by_side_bytes(pdf_bytes: bytes) -> bytes:
    """The sample paper as a side_by_side file: original left, translation right.

    PaperFlow puts the two pages side by side at their own size on a page twice
    as wide, so the left half is the original page exactly — same boxes, same
    coordinates — and the right half is its re-typeset translation.
    """
    src = fitz.open(stream=pdf_bytes, filetype="pdf")
    width = src.load_page(0).rect.width
    height = src.load_page(0).rect.height
    trans = fitz.open()
    for _ in range(src.page_count):
        page = trans.new_page(width=width, height=height)
        for offset, line in enumerate(_TRANSLATIONS):
            page.insert_text(
                (72, 72 + offset * 28), line, fontname="china-s", fontsize=11
            )
    out = fitz.open()
    for index in range(src.page_count):
        page = out.new_page(width=width * 2, height=height)
        page.show_pdf_page(fitz.Rect(0, 0, width, height), src, index)
        page.show_pdf_page(fitz.Rect(width, 0, width * 2, height), trans, index)
    data = out.tobytes()
    for doc in (src, trans, out):
        doc.close()
    return data


def _upload(client, data: bytes, name: str = "sample.pdf") -> str:
    resp = client.post(
        "/api/papers/upload",
        files={"file": (name, data, "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_evidence_becomes_native_annotations(client, paper_id):
    out = _write(client, paper_id)
    assert out["written"] == 2, out

    facts = _evidence_facts(served_pdf(client, paper_id))
    assert len(facts) == 2
    assert {f["kind"] for f in facts} == {"Highlight"}
    assert any("Transformer" in (f["content"] or "") for f in facts)


def test_evidence_without_rects_is_located_by_text(client, paper_id):
    out = _write(client, paper_id, [EVIDENCE[0]])
    assert out["written"] == 1, out

    facts = _evidence_facts(served_pdf(client, paper_id))
    assert len(facts) == 1
    assert "Transformer" in facts[0]["content"]


def test_writing_twice_does_not_duplicate(client, paper_id):
    assert _write(client, paper_id)["written"] == 2

    second = _write(client, paper_id)
    assert second["written"] == 0
    assert second["skipped"] == 2
    assert len(_evidence_facts(served_pdf(client, paper_id))) == 2


def test_highlight_sync_keeps_evidence(client, paper_id, sync_enabled):
    _write(client, paper_id)
    resp = client.post(
        f"/api/papers/{paper_id}/highlights",
        json={"page": 0, "rects": [[72.0, 120.0, 400.0, 140.0]], "text": "Abstract"},
    )
    assert resp.status_code == 200, resp.text

    sync = client.post(f"/api/papers/{paper_id}/highlights/sync-pdf")
    assert sync.status_code == 200, sync.text

    assert len(_evidence_facts(served_pdf(client, paper_id))) == 2


def test_evidence_can_be_cleared(client, paper_id):
    _write(client, paper_id)
    resp = client.delete(f"/api/papers/{paper_id}/evidence/pdf")
    assert resp.status_code == 200, resp.text
    assert resp.json()["removed"] == 2
    assert _evidence_facts(served_pdf(client, paper_id)) == []


def test_evidence_lands_on_the_translated_pages_of_a_dual(client, paper_id, pdf_bytes):
    dual = _write_dual(paper_id, pdf_bytes)

    out = _write(client, paper_id, target="dual", side="translated")
    assert out["written"] == 2, out

    facts = _evidence_facts(dual.read_bytes())
    assert len(facts) == 2
    # Source page p is page 2p+1 of a dual: its translated page.
    assert sorted(f["page"] for f in facts) == [1, 3]
    assert _evidence_facts(served_pdf(client, paper_id)) == []


def test_both_writes_the_source_and_the_translation(client, paper_id, pdf_bytes):
    dual = _write_dual(paper_id, pdf_bytes)

    out = _write(client, paper_id, target="both", side="translated")
    assert out["written"] == 4, out
    assert len(out["targets"]) == 2

    assert len(_evidence_facts(served_pdf(client, paper_id))) == 2
    assert len(_evidence_facts(dual.read_bytes())) == 2


def test_evidence_lands_on_both_sides_of_a_dual(client, paper_id, pdf_bytes):
    """A bilingual file is read two-up: the mark must appear on both pages."""
    dual = _write_dual(paper_id, pdf_bytes)

    out = _write(client, paper_id, target="dual", side="both")
    assert out["written"] == 4, out

    facts = _evidence_facts(dual.read_bytes())
    # Source page p is page 2p of a dual, and its translation is the next one.
    assert sorted(f["page"] for f in facts) == [0, 1, 2, 3]
    assert _evidence_facts(served_pdf(client, paper_id)) == []


def test_writing_both_sides_twice_does_not_stack(client, paper_id, pdf_bytes):
    dual = _write_dual(paper_id, pdf_bytes)
    _write(client, paper_id, target="dual", side="both")

    again = _write(client, paper_id, target="dual", side="both")
    assert again["written"] == 0, again
    assert len(_evidence_facts(dual.read_bytes())) == 4


def test_one_evidence_yields_one_mark_per_side(client, paper_id):
    """Two items on the same spot are one pair, not two stacked highlights."""
    spot = [[72.0, 120.0, 400.0, 140.0]]
    out = _write(
        client,
        paper_id,
        [
            {"id": "E1", "quote": "We propose the Transformer.", "why": "a",
             "page": 0, "rects": spot},
            {"id": "E2", "quote": "Attention is all you need.", "why": "b",
             "page": 0, "rects": spot},
        ],
    )
    assert out["written"] == 1, out
    assert out["skipped"] == 1, out
    assert len(_evidence_facts(served_pdf(client, paper_id))) == 1


def test_a_highlight_is_mirrored_when_the_target_is_a_dual(
    client, paper_id, pdf_bytes
):
    """The paper is read in the bilingual file: a mark on one side has to show
    on the other, and it is placed from the original side."""
    dual = _write_dual(paper_id, pdf_bytes)
    link = client.post(
        f"/api/papers/{paper_id}/pdf-target", json={"path": str(dual)}
    )
    assert link.status_code == 200, link.text

    make_highlight(client, paper_id, page=0, rects=[[72.0, 120.0, 400.0, 140.0]])

    facts = [f for f in annot_facts(dual.read_bytes()) if f["title"] == "Gloss"]
    assert sorted(f["page"] for f in facts) == [0, 1], facts


def test_deleting_a_highlight_removes_its_mirror(client, paper_id, pdf_bytes):
    dual = _write_dual(paper_id, pdf_bytes)
    client.post(f"/api/papers/{paper_id}/pdf-target", json={"path": str(dual)})

    hid = make_highlight(
        client, paper_id, page=0, rects=[[72.0, 120.0, 400.0, 140.0]]
    ).json()["id"]
    resp = client.delete(f"/api/highlights/{hid}")
    assert resp.status_code == 200, resp.text

    assert [f for f in annot_facts(dual.read_bytes()) if f["title"] == "Gloss"] == []


def test_an_imported_bilingual_file_is_recognised(client, pdf_bytes):
    pid = _upload(client, _cjk_dual_bytes(pdf_bytes), "paper-dual.pdf")
    try:
        status = client.get(f"/api/papers/{pid}/evidence/pdf").json()
        assert status["dual"]["available"] is True, status
    finally:
        client.delete(f"/api/papers/{pid}")


def test_a_bilingual_file_imported_under_another_name_is_detected(
    client, pdf_bytes
):
    """Gloss renames the import, so the answer has to come from the pages."""
    pid = _upload(client, _cjk_dual_bytes(pdf_bytes), "我的论文.pdf")
    try:
        status = client.get(f"/api/papers/{pid}/evidence/pdf").json()
        assert status["dual"]["available"] is True, status
    finally:
        client.delete(f"/api/papers/{pid}")


def test_a_plain_paper_is_not_treated_as_bilingual(client, pdf_bytes):
    pid = _upload(client, pdf_bytes, "sample.pdf")
    try:
        status = client.get(f"/api/papers/{pid}/evidence/pdf").json()
        assert status["dual"]["available"] is False, status
    finally:
        client.delete(f"/api/papers/{pid}")


def test_a_highlight_in_an_imported_bilingual_file_lands_on_both_pages(
    client, pdf_bytes
):
    """Drawn on the left-hand page, it is marked on the one facing it too."""
    pid = _upload(client, _cjk_dual_bytes(pdf_bytes), "paper-dual.pdf")
    try:
        make_highlight(client, pid, page=0, rects=[[72.0, 120.0, 400.0, 140.0]])

        facts = [
            f for f in annot_facts(served_pdf(client, pid)) if f["title"] == "Gloss"
        ]
        assert sorted(f["page"] for f in facts) == [0, 1], facts
    finally:
        client.delete(f"/api/papers/{pid}")


def test_evidence_in_an_imported_bilingual_file_lands_on_both_pages(
    client, pdf_bytes
):
    pid = _upload(client, _cjk_dual_bytes(pdf_bytes), "paper-dual.pdf")
    try:
        out = _write(client, pid, evidence=DUAL_EVIDENCE, target="auto", side="both")
        assert out["written"] == 4, out

        facts = _evidence_facts(served_pdf(client, pid))
        assert sorted(f["page"] for f in facts) == [0, 1, 2, 3], facts
    finally:
        client.delete(f"/api/papers/{pid}")


def test_a_highlight_in_a_side_by_side_file_is_mirrored(client, pdf_bytes):
    """PaperFlow's side_by_side: the reader marks the left column."""
    pid = _upload(client, _side_by_side_bytes(pdf_bytes), "paper-side_by_side.pdf")
    try:
        make_highlight(client, pid, page=0, rects=[[72.0, 120.0, 400.0, 140.0]])

        data = served_pdf(client, pid)
        doc = fitz.open(stream=data, filetype="pdf")
        half = doc.load_page(0).rect.width / 2
        doc.close()
        facts = [f for f in annot_facts(data) if f["title"] == "Gloss"]

        # One on the column that was marked, one on the translation beside it.
        assert len([f for f in facts if f["rect"][0] < half]) == 1, facts
        assert len([f for f in facts if f["rect"][0] >= half]) == 1, facts
    finally:
        client.delete(f"/api/papers/{pid}")


def test_a_side_by_side_file_imported_under_another_name_is_detected(
    client, pdf_bytes
):
    pid = _upload(client, _side_by_side_bytes(pdf_bytes), "论文.pdf")
    try:
        make_highlight(client, pid, page=0, rects=[[72.0, 120.0, 400.0, 140.0]])

        facts = [
            f for f in annot_facts(served_pdf(client, pid)) if f["title"] == "Gloss"
        ]
        assert len(facts) == 2, facts
    finally:
        client.delete(f"/api/papers/{pid}")


def test_evidence_in_a_side_by_side_file_lands_on_both_columns(client, pdf_bytes):
    pid = _upload(client, _side_by_side_bytes(pdf_bytes), "paper-side_by_side.pdf")
    try:
        out = _write(client, pid, evidence=EVIDENCE, target="auto", side="both")
        assert out["written"] == 4, out

        data = served_pdf(client, pid)
        doc = fitz.open(stream=data, filetype="pdf")
        half = doc.load_page(0).rect.width / 2
        doc.close()
        facts = _evidence_facts(data)

        assert len([f for f in facts if f["rect"][0] < half]) == 2, facts
        assert len([f for f in facts if f["rect"][0] >= half]) == 2, facts
    finally:
        client.delete(f"/api/papers/{pid}")


def test_evidence_already_in_the_pdf_gets_its_mirror_later(client, pdf_bytes):
    """Exported before Gloss mirrored: the translation is filled in on a rerun."""
    pid = _upload(client, _side_by_side_bytes(pdf_bytes), "paper-side_by_side.pdf")
    try:
        # What an older build left behind: the original column asked for by name.
        first = _write(client, pid, evidence=EVIDENCE, target="dual", side="original")
        assert first["written"] == 2, first

        second = _write(client, pid, evidence=EVIDENCE, target="auto", side="both")
        assert second["written"] == 2, second  # the two missing mirrors only

        data = served_pdf(client, pid)
        doc = fitz.open(stream=data, filetype="pdf")
        half = doc.load_page(0).rect.width / 2
        doc.close()
        facts = _evidence_facts(data)

        assert len([f for f in facts if f["rect"][0] < half]) == 2, facts
        assert len([f for f in facts if f["rect"][0] >= half]) == 2, facts
    finally:
        client.delete(f"/api/papers/{pid}")


def _columns_in(path) -> dict[str, int]:
    """How a file's evidence annotations split across its two columns."""
    doc = fitz.open(str(path))
    half = doc.load_page(0).rect.width / 2
    counts = {"left": 0, "right": 0}
    try:
        for index in range(doc.page_count):
            for annot in doc.load_page(index).annots():
                title = (annot.info.get("title") or "").strip()
                if not title.startswith("Gloss Evidence"):
                    continue
                counts["right" if annot.rect.x0 >= half else "left"] += 1
    finally:
        doc.close()
    return counts


def _columns(client, paper_id) -> dict[str, int]:
    return _columns_in(store.pdf_path(paper_id))


def test_auto_marks_both_columns_and_writing_twice_adds_nothing(
    client, pdf_bytes
):
    """The default choice fills the translation column too.

    Writing again is how a file marked by an older Gloss gets the column it was
    missing: it must add that one, and leave the other exactly as it was.
    """
    pid = _upload(client, _side_by_side_bytes(pdf_bytes), "paper-side_by_side.pdf")
    try:
        _write(client, pid)
        first = _columns(client, pid)
        assert first["left"] == 2, first
        assert first["right"] == 2, first

        _write(client, pid)
        assert _columns(client, pid) == first, (first, _columns(client, pid))
    finally:
        client.delete(f"/api/papers/{pid}")


def test_auto_marks_both_columns_of_a_linked_bilingual_file(client, pdf_bytes):
    """Gloss reads the source; PaperFlow's file, linked from Zotero, is marked.

    Its original column is a whole source page, so the evidence page numbers
    index it as they stand — the translation beside it still gets its mark.
    """
    pid = _upload(client, pdf_bytes, "paper.pdf")
    try:
        outside = store.pdf_path(pid).with_name("original-side_by_side.pdf")
        outside.write_bytes(_side_by_side_bytes(pdf_bytes))
        store.set_paper_source_pdf(pid, str(outside))

        _write(client, pid)

        columns = _columns_in(outside)
        assert columns == {"left": 2, "right": 2}, columns
    finally:
        client.delete(f"/api/papers/{pid}")


def test_a_highlight_is_mirrored_in_a_bilingual_file_outside_gloss(client, pdf_bytes):
    """The reader reads the source in Gloss; PaperFlow's file lies beside it.

    This is the Zotero case: the marked file is not the one on screen, so a page
    of the source is a page of it, and the mark has to appear on both columns.
    """
    pid = _upload(client, pdf_bytes, "paper.pdf")
    try:
        outside = store.pdf_path(pid).with_name("original-side_by_side.pdf")
        outside.write_bytes(_side_by_side_bytes(pdf_bytes))
        store.set_paper_source_pdf(pid, str(outside))

        make_highlight(client, pid, page=0, rects=[[72.0, 120.0, 400.0, 140.0]])

        doc = fitz.open(str(outside))
        half = doc.load_page(0).rect.width / 2
        found: list[float] = []
        for index in range(doc.page_count):
            for annot in doc.load_page(index).annots():
                if annot.info.get("title") == "Gloss":
                    found.append(annot.rect.x0)
        doc.close()

        assert len(found) == 2, found
        assert len([x for x in found if x < half]) == 1, found
        assert len([x for x in found if x >= half]) == 1, found
    finally:
        client.delete(f"/api/papers/{pid}")


def test_a_note_reaches_the_translation_beside_it(client, pdf_bytes):
    """Both layouts: what the reader writes, the translation carries too."""
    for name, data in (
        ("paper-dual.pdf", _cjk_dual_bytes(pdf_bytes)),
        ("paper-side_by_side.pdf", _side_by_side_bytes(pdf_bytes)),
    ):
        pid = _upload(client, data, name)
        try:
            make_highlight(
                client,
                pid,
                page=0,
                rects=[[72.0, 120.0, 400.0, 140.0]],
                text="We propose the Transformer.",
                note="这里是核心贡献",
            )

            facts = [
                f for f in annot_facts(served_pdf(client, pid)) if f["title"] == "Gloss"
            ]
            assert len(facts) == 2, (name, facts)
            assert all("这里是核心贡献" in (f["content"] or "") for f in facts), facts
        finally:
            client.delete(f"/api/papers/{pid}")


def test_a_highlight_reaches_both_columns_of_a_linked_bilingual_file(
    client, pdf_bytes
):
    """Gloss reads the source; the mark reaches the translation beside it.

    PaperFlow's file, linked from Zotero, keeps a source page per page, so the
    copy goes on the very page — from the layout, with no sidecar to go by.
    """
    pid = _upload(client, pdf_bytes, "paper.pdf")
    try:
        outside = store.pdf_path(pid).with_name("original-side_by_side.pdf")
        outside.write_bytes(_side_by_side_bytes(pdf_bytes))
        store.set_paper_source_pdf(pid, str(outside))

        make_highlight(client, pid, page=0, rects=[[72.0, 120.0, 400.0, 140.0]])

        facts = [
            f for f in annot_facts(outside.read_bytes()) if f["title"] == "Gloss"
        ]
        assert len(facts) == 2, facts
        assert [f for f in facts if f["rect"][0] < 612.0], facts
        assert [f for f in facts if f["rect"][0] >= 612.0], facts
    finally:
        client.delete(f"/api/papers/{pid}")


def test_a_mirrored_highlight_carries_its_note_to_the_other_column(
    client, pdf_bytes
):
    """Both columns read the same note — the point of pairing them.

    A mark without its comment would leave the translation annotated with a
    colour and nothing to read.
    """
    pid = _upload(client, pdf_bytes, "paper.pdf")
    try:
        outside = store.pdf_path(pid).with_name("original-side_by_side.pdf")
        outside.write_bytes(_side_by_side_bytes(pdf_bytes))
        store.set_paper_source_pdf(pid, str(outside))

        made = make_highlight(
            client, pid, page=0, rects=[[72.0, 120.0, 400.0, 140.0]]
        ).json()
        resp = client.patch(f"/api/highlights/{made['id']}", json={"note": "核心主张"})
        assert resp.status_code == 200, resp.text

        facts = [
            f for f in annot_facts(outside.read_bytes()) if f["title"] == "Gloss"
        ]
        assert len(facts) == 2, facts
        assert [f for f in facts if f["rect"][0] < 612.0], facts
        assert [f for f in facts if f["rect"][0] >= 612.0], facts
        assert all("核心主张" in (f["content"] or "") for f in facts), facts
    finally:
        client.delete(f"/api/papers/{pid}")


def test_editing_a_highlight_edits_its_mirror(client, pdf_bytes):
    """Recolouring one side recolours the translation facing it."""
    pid = _upload(client, _side_by_side_bytes(pdf_bytes), "paper-side_by_side.pdf")
    try:
        made = make_highlight(
            client, pid, page=0, rects=[[72.0, 120.0, 400.0, 140.0]], color="#28ca42"
        ).json()
        resp = client.patch(
            f"/api/highlights/{made['id']}", json={"color": "#ff0000"}
        )
        assert resp.status_code == 200, resp.text

        facts = [
            f for f in annot_facts(served_pdf(client, pid)) if f["title"] == "Gloss"
        ]
        assert len(facts) == 2, facts
        # Both are red now, and neither was dropped or duplicated.
        assert all(_is_red(f["stroke"]) for f in facts), facts
    finally:
        client.delete(f"/api/papers/{pid}")


def _is_red(stroke: list[float]) -> bool:
    """Red is the first channel and well ahead of the others."""
    return len(stroke) == 3 and stroke[0] > 0.7 and stroke[1] < 0.3


def test_status_counts_the_selected_target(client, paper_id, pdf_bytes):
    _write_dual(paper_id, pdf_bytes)
    _write(client, paper_id, target="dual", side="translated")

    def status(target: str) -> dict:
        resp = client.get(
            f"/api/papers/{paper_id}/evidence/pdf?target={target}&side=translated"
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    assert status("dual")["embedded"] == 2
    assert status("dual")["dual"]["available"] is True
    # The source itself was untouched, so it must not claim those annotations.
    assert status("original")["embedded"] == 0


def test_clearing_only_touches_the_selected_target(client, paper_id, pdf_bytes):
    dual = _write_dual(paper_id, pdf_bytes)
    _write(client, paper_id, target="both", side="translated")

    resp = client.delete(
        f"/api/papers/{paper_id}/evidence/pdf?target=dual&side=translated"
    )
    assert resp.json()["removed"] == 2

    assert _evidence_facts(dual.read_bytes()) == []
    assert len(_evidence_facts(served_pdf(client, paper_id))) == 2


def test_unlocatable_evidence_is_reported(client, paper_id):
    out = _write(
        client,
        paper_id,
        [{"id": "E9", "quote": "这句话不在文档里", "why": "", "page": 0, "rects": []}],
    )
    assert out["written"] == 0
    assert out["results"][0]["error"] == "not found in pdf"
    assert _evidence_facts(served_pdf(client, paper_id)) == []


def _right_column_rects(path) -> list[tuple]:
    doc = fitz.open(str(path))
    half = doc.load_page(0).rect.width / 2
    found: list[tuple] = []
    try:
        for index in range(doc.page_count):
            for annot in doc.load_page(index).annots():
                title = (annot.info.get("title") or "").strip()
                if not title.startswith("Gloss Evidence"):
                    continue
                if annot.rect.x0 >= half:
                    found.append(tuple(round(v, 1) for v in annot.rect))
    finally:
        doc.close()
    return sorted(found)


def _widen_first_right_column_annot(path, by: float) -> bool:
    """Make one mirror cover the paragraph, the way an older build left it.

    A highlight's box cannot be moved in place, so the annotation is written
    again over the wider stretch of lines, saying the same thing.
    """
    doc = fitz.open(str(path))
    half = doc.load_page(0).rect.width / 2
    data: bytes | None = None
    try:
        for index in range(doc.page_count):
            page = doc.load_page(index)
            for annot in list(page.annots()):
                title = (annot.info.get("title") or "").strip()
                if not title.startswith("Gloss Evidence"):
                    continue
                if annot.rect.x0 < half:
                    continue
                rect = fitz.Rect(annot.rect)
                info = annot.info
                page.delete_annot(annot)
                made = page.add_highlight_annot(
                    fitz.Rect(rect.x0, rect.y0 - by, rect.x1, rect.y1 + by)
                )
                made.set_info(
                    title=info.get("title") or "",
                    content=info.get("content") or "",
                )
                made.update()
                data = doc.tobytes()
                break
            if data is not None:
                break
    finally:
        doc.close()
    if data is None:
        return False
    Path(path).write_bytes(data)
    return True


def test_a_mirror_on_the_wrong_lines_is_moved_on_a_rerun(client, pdf_bytes):
    """What an older build wrote — the paragraph, not the sentence — gets fixed.

    Re-running the export is the only thing a reader can do about an export
    already in the file, so it has to move a mark onto the lines the pairing now
    gives instead of leaving the old one where it is.
    """
    pid = _upload(client, _side_by_side_bytes(pdf_bytes), "paper-side_by_side.pdf")
    try:
        _write(client, pid)
        before = _right_column_rects(store.pdf_path(pid))
        assert len(before) == 2, before

        assert _widen_first_right_column_annot(store.pdf_path(pid), 40.0)
        assert _right_column_rects(store.pdf_path(pid)) != before

        _write(client, pid)
        assert _right_column_rects(store.pdf_path(pid)) == before
    finally:
        client.delete(f"/api/papers/{pid}")
