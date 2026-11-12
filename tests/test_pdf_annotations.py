"""Annotations that live in the PDF file rather than in Gloss's database.

Note evidence written for a reader, and marks Zotero or another reader left in
the file, exist only inside the PDF — Gloss used to draw its own highlights from
the database and never read the file back, so none of them were visible. This
covers reading them out and deleting one where it sits.
"""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from app.library import store
from pdf_helpers import annot_facts, make_highlight, served_pdf

EVIDENCE = [
    {
        "id": "E1",
        "quote": "We propose the Transformer, a model based solely on attention mechanisms.",
        "why": "核心主张",
        "page": 0,
        "rects": [],
    },
]


def _list(client, paper_id: str) -> list[dict]:
    resp = client.get(f"/api/papers/{paper_id}/pdf-annotations")
    assert resp.status_code == 200, resp.text
    return resp.json()["annotations"]


def _write_evidence(client, paper_id: str) -> None:
    resp = client.post(
        f"/api/papers/{paper_id}/evidence/pdf",
        json={"evidence": EVIDENCE, "target": "original", "side": "original"},
    )
    assert resp.status_code == 200, resp.text


def _leave_mark(path: Path, title: str, box=(72.0, 300.0, 400.0, 320.0)) -> None:
    """Write a highlight the way a reader outside Gloss would."""
    doc = fitz.open(str(path))
    try:
        page = doc.load_page(0)  # kept alive: the annot holds only a weak ref
        annot = page.add_highlight_annot(fitz.Rect(*box))
        annot.set_colors(stroke=(0.91, 0.8, 0.2))
        annot.set_info(content=f"left by {title}", title=title)
        annot.update()
        doc.saveIncr()
    finally:
        doc.close()


def test_a_fresh_paper_has_no_file_annotations(client, paper_id) -> None:
    assert _list(client, paper_id) == []


def test_evidence_written_into_the_file_is_listed(client, paper_id) -> None:
    _write_evidence(client, paper_id)

    marks = [a for a in _list(client, paper_id) if a["kind"] == "gloss_evidence"]

    assert marks, "evidence in the PDF stayed invisible to Gloss"
    assert marks[0]["page"] == 0
    assert marks[0]["rects"], "a mark without geometry cannot be drawn or clicked"
    assert marks[0]["source"] == "copy"


def test_another_readers_mark_is_listed_as_external(client, paper_id) -> None:
    _leave_mark(store.pdf_path(paper_id), "Zotero")

    marks = _list(client, paper_id)

    assert len(marks) == 1
    assert marks[0]["kind"] == "external"
    assert marks[0]["title"] == "Zotero"
    assert marks[0]["content"] == "left by Zotero"
    assert marks[0]["type"] == "Highlight"


def test_a_database_highlight_is_tagged_gloss(client, paper_id, sync_enabled) -> None:
    make_highlight(client, paper_id)

    kinds = {a["kind"] for a in _list(client, paper_id)}

    # Tagged so the PDF layer can skip it: the database layer already draws it.
    assert "gloss" in kinds


def test_deleting_one_leaves_the_rest(client, paper_id) -> None:
    path = store.pdf_path(paper_id)
    _leave_mark(path, "First", (72.0, 300.0, 400.0, 320.0))
    _leave_mark(path, "Second", (72.0, 340.0, 400.0, 360.0))

    before = _list(client, paper_id)
    assert len(before) == 2
    doomed = before[0]
    resp = client.delete(
        f"/api/papers/{paper_id}/pdf-annotations/{doomed['xref']}"
        f"?source={doomed['source']}"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["removed"] == 1

    assert [a["title"] for a in _list(client, paper_id)] == ["Second"]
    assert len(annot_facts(served_pdf(client, paper_id))) == 1


def test_deleting_an_evidence_mark_removes_it_from_the_file(client, paper_id) -> None:
    _write_evidence(client, paper_id)
    mark = _list(client, paper_id)[0]

    resp = client.delete(
        f"/api/papers/{paper_id}/pdf-annotations/{mark['xref']}?source={mark['source']}"
    )
    assert resp.status_code == 200, resp.text

    assert _list(client, paper_id) == []
    assert annot_facts(served_pdf(client, paper_id)) == []


def test_sticky_notes_are_not_listed(client, paper_id) -> None:
    """Only text markup is listed: a note carries no geometry to draw."""
    path = store.pdf_path(paper_id)
    doc = fitz.open(str(path))
    try:
        doc.load_page(0).add_text_annot(fitz.Point(90, 400), "a comment")
        doc.saveIncr()
    finally:
        doc.close()

    assert _list(client, paper_id) == []


@pytest.fixture()
def original_pdf(tmp_path, pdf_bytes) -> Path:
    """A PDF outside Gloss, standing in for the Zotero attachment."""
    path = tmp_path / "zotero-storage" / "Attention Is All You Need.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pdf_bytes)
    return path


def test_a_linked_original_is_read_too(client, paper_id, original_pdf, sync_enabled) -> None:
    _leave_mark(original_pdf, "Zotero")
    linked = client.post(
        f"/api/papers/{paper_id}/pdf-target", json={"path": str(original_pdf)}
    )
    assert linked.status_code == 200, linked.text

    marks = _list(client, paper_id)

    assert [a["source"] for a in marks] == ["original"]
    assert marks[0]["title"] == "Zotero"
