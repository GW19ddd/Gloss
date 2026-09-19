"""Annotations must land in the paper's *original* PDF once it is linked.

A paper imported into Gloss normally only has the copy inside Gloss's data
directory. Linking an original (the Zotero attachment, say) has to redirect
every subsequent write to that file — and leave Gloss's own copy alone.
"""
from __future__ import annotations

import pytest

from pdf_helpers import annot_facts, make_highlight, served_pdf


@pytest.fixture()
def original_pdf(tmp_path, pdf_bytes):
    """A PDF living outside Gloss, standing in for the Zotero attachment."""
    path = tmp_path / "zotero-storage" / "Attention Is All You Need.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pdf_bytes)
    return path


def _link(client, paper_id, path):
    return client.post(f"/api/papers/{paper_id}/pdf-target", json={"path": str(path)})


def test_linked_original_receives_annotations(client, paper_id, original_pdf, sync_enabled):
    linked = _link(client, paper_id, original_pdf)
    assert linked.status_code == 200, linked.text
    assert linked.json()["target"]["is_original"] is True

    make_highlight(client, paper_id)

    # The original now carries the annotation…
    assert len(annot_facts(original_pdf.read_bytes())) == 1
    # …and Gloss's own copy is left untouched.
    assert annot_facts(served_pdf(client, paper_id)) == []


def test_without_a_link_annotations_go_to_gloss_copy(client, paper_id, original_pdf, sync_enabled):
    status = client.get(f"/api/papers/{paper_id}/pdf-target")
    assert status.json()["is_original"] is False

    make_highlight(client, paper_id)
    assert len(annot_facts(served_pdf(client, paper_id))) == 1
    assert annot_facts(original_pdf.read_bytes()) == []


def test_linking_pushes_existing_highlights_into_the_original(
    client, paper_id, original_pdf, sync_enabled
):
    make_highlight(client, paper_id, text="already noted")
    assert annot_facts(original_pdf.read_bytes()) == []

    linked = _link(client, paper_id, original_pdf)
    assert linked.json()["sync"]["written"] == 1
    facts = annot_facts(original_pdf.read_bytes())
    assert len(facts) == 1
    assert "already noted" in facts[0]["content"]


def test_unlinking_returns_to_gloss_copy(client, paper_id, original_pdf, sync_enabled):
    _link(client, paper_id, original_pdf)

    unlinked = client.delete(f"/api/papers/{paper_id}/pdf-target")
    assert unlinked.status_code == 200, unlinked.text
    assert unlinked.json()["is_original"] is False

    # xrefs from the original are stale now, so the writer recreates the annot.
    make_highlight(client, paper_id)
    assert len(annot_facts(served_pdf(client, paper_id))) == 1
    assert len(annot_facts(original_pdf.read_bytes())) == 0


def test_link_rejects_unusable_paths(client, paper_id, tmp_path, sync_enabled):
    internal = client.get(f"/api/papers/{paper_id}/pdf-target").json()["path"]

    # Gloss's own working copy is not an "original".
    assert _link(client, paper_id, internal).status_code == 400
    # Neither is a missing file, a directory, nor a non-PDF.
    assert _link(client, paper_id, tmp_path / "nope.pdf").status_code == 404
    assert _link(client, paper_id, tmp_path).status_code == 400
    not_pdf = tmp_path / "notes.txt"
    not_pdf.write_text("hello")
    assert _link(client, paper_id, not_pdf).status_code == 400


def test_missing_original_is_reported(client, paper_id, original_pdf, sync_enabled):
    _link(client, paper_id, original_pdf)
    original_pdf.unlink()

    info = client.get(f"/api/papers/{paper_id}/pdf-target")
    assert info.json()["linked_missing"] is True
    # Writing falls back to Gloss's copy rather than failing outright.
    assert info.json()["is_original"] is False
