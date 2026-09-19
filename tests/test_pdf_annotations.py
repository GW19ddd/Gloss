"""Highlights must also exist *inside* the PDF file as native annotations.

The app is still driven only through its HTTP API; we just re-download the
served PDF and inspect it with PyMuPDF, exactly like Acrobat / Zotero would.
"""
from __future__ import annotations

from pdf_helpers import annot_facts, make_highlight, served_pdf


def test_highlight_is_written_into_the_pdf(client, paper_id, sync_enabled):
    created = make_highlight(client, paper_id)
    highlight = created.json()
    # The API reports which PDF object the highlight became.
    assert highlight["pdf_xref"]

    annots = annot_facts(served_pdf(client, paper_id))
    assert len(annots) == 1
    annot = annots[0]
    assert annot["kind"] == "Highlight"
    assert annot["title"] == "Gloss"
    assert "We propose the Transformer." in annot["content"]
    stroke = annot["stroke"]
    assert abs(stroke[0] - 40 / 255) < 0.01
    assert abs(stroke[1] - 202 / 255) < 0.01
    assert abs(stroke[2] - 66 / 255) < 0.01


def test_editing_a_highlight_updates_the_pdf_annotation(client, paper_id, sync_enabled):
    hid = make_highlight(client, paper_id).json()["id"]

    patched = client.patch(
        f"/api/highlights/{hid}",
        json={"color": "#ff0000", "note": "key result"},
    )
    assert patched.status_code == 200, patched.text

    annots = annot_facts(served_pdf(client, paper_id))
    # Updated in place — no duplicate left behind.
    assert len(annots) == 1
    assert abs(annots[0]["stroke"][0] - 1.0) < 0.01
    assert "key result" in annots[0]["content"]


def test_deleting_a_highlight_removes_the_pdf_annotation(client, paper_id, sync_enabled):
    hid = make_highlight(client, paper_id).json()["id"]
    assert len(annot_facts(served_pdf(client, paper_id))) == 1

    assert client.delete(f"/api/highlights/{hid}").status_code == 200
    assert annot_facts(served_pdf(client, paper_id)) == []


def test_sync_endpoint_rebuilds_annotations_from_the_database(
    client, paper_id, sync_enabled
):
    make_highlight(client, paper_id, text="first")
    make_highlight(
        client,
        paper_id,
        page=1,
        rects=[[72.0, 90.0, 300.0, 106.0]],
        text="second",
    )

    result = client.post(f"/api/papers/{paper_id}/highlights/sync-pdf")
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["total"] == 2
    assert body["written"] == 2
    assert body["embedded"] == 2
    # A rebuild must not duplicate annotations.
    assert len(annot_facts(served_pdf(client, paper_id))) == 2
    assert all(h["pdf_xref"] for h in body["highlights"])


def test_sync_can_be_disabled_and_repaired_later(client, paper_id, sync_enabled):
    off = client.post("/api/settings", json={"sync_highlights_to_pdf": False})
    assert off.status_code == 200, off.text

    created = make_highlight(client, paper_id)
    assert created.json()["pdf_xref"] is None
    assert annot_facts(served_pdf(client, paper_id)) == []

    # Turning it back on does not silently rewrite history — the explicit
    # sync action does.
    client.post("/api/settings", json={"sync_highlights_to_pdf": True})
    result = client.post(f"/api/papers/{paper_id}/highlights/sync-pdf")
    assert result.json()["written"] == 1
    assert len(annot_facts(served_pdf(client, paper_id))) == 1
