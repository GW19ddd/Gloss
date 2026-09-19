"""Shared helpers for inspecting the PDFs the app serves or writes.

Tests stay black-box (they only talk HTTP), but they still need to verify what
actually ended up *inside* a PDF file, the way Acrobat / Zotero would read it.
"""
from __future__ import annotations


def served_pdf(client, paper_id: str) -> bytes:
    """Fetch the PDF Gloss itself serves for a paper."""
    resp = client.get(f"/api/papers/{paper_id}/pdf")
    assert resp.status_code == 200, resp.text
    return resp.content


def annot_facts(data: bytes) -> list[dict]:
    """Every annotation in a PDF, copied out while its page is still alive.

    A PyMuPDF annotation becomes unusable once its owning page is garbage
    collected, so everything is read eagerly.
    """
    import fitz

    doc = fitz.open(stream=data, filetype="pdf")
    try:
        facts = []
        for pno in range(doc.page_count):
            page = doc.load_page(pno)
            for annot in page.annots():
                facts.append({
                    "kind": annot.type[1],
                    "title": annot.info.get("title"),
                    "content": annot.info.get("content"),
                    "stroke": list(annot.colors.get("stroke") or []),
                })
        return facts
    finally:
        doc.close()


def make_highlight(client, paper_id: str, **overrides):
    response = client.post(
        f"/api/papers/{paper_id}/highlights",
        json={
            "page": 0,
            "rects": [[72.0, 120.0, 400.0, 140.0]],
            "text": "We propose the Transformer.",
            "color": "#28ca42",
            **overrides,
        },
    )
    assert response.status_code == 200, response.text
    return response
