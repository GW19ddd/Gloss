"""The note the reader sees: AI draft, their own edit, and the versions between.

Two promises are under test here. A regeneration may replace the draft, but the
reader's own words are kept next to it and can be brought back. And a failed
generation is not a note: what the reader had stays exactly as it was.
"""
from __future__ import annotations

from app.library import store
from pdf_helpers import annot_facts, served_pdf

LANG = "zh"
DRAFT = "# 一句话概述\n\nAI 写的草稿 [原文][E1]"
EVIDENCE = [
    {
        "id": "E1",
        "quote": "We propose the Transformer, a model based solely on attention mechanisms.",
        "why": "核心主张",
        "page": 0,
        "rects": [],
    }
]


def state(client, paper_id: str) -> dict:
    resp = client.get(f"/api/papers/{paper_id}/notes/state?language={LANG}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def seed_draft(paper_id: str, markdown: str = DRAFT) -> None:
    store.cache_set(
        paper_id,
        f"notes2:{LANG}",
        {"markdown": markdown, "evidence": EVIDENCE, "scope": "full"},
    )


def seed_history(paper_id: str, versions: list[dict]) -> None:
    store.cache_set(paper_id, f"notes_history:{LANG}", versions)


# --- before anything is generated --------------------------------------------

def test_state_is_empty_before_a_note_exists(client, paper_id):
    assert state(client, paper_id) == {
        "markdown": "",
        "evidence": [],
        "edited": None,
        "history": [],
        "language": LANG,
    }


# --- the reader's own edit ----------------------------------------------------

def test_an_edit_is_saved_next_to_the_draft(client, paper_id):
    seed_draft(paper_id)

    resp = client.put(
        f"/api/papers/{paper_id}/notes/edit",
        json={"language": LANG, "markdown": "我自己写的理解"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["edited"] == "我自己写的理解"

    # The draft survives underneath: the two are never merged into one text.
    now = state(client, paper_id)
    assert now["edited"] == "我自己写的理解"
    assert now["markdown"] == DRAFT
    assert now["evidence"][0]["id"] == "E1"


def test_reverting_drops_the_edit_but_keeps_the_draft(client, paper_id):
    seed_draft(paper_id)
    client.put(
        f"/api/papers/{paper_id}/notes/edit",
        json={"language": LANG, "markdown": "临时改动"},
    )

    resp = client.post(f"/api/papers/{paper_id}/notes/revert?language={LANG}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["edited"] is None
    assert state(client, paper_id)["markdown"] == DRAFT


def test_an_edit_in_one_language_does_not_leak_into_another(client, paper_id):
    seed_draft(paper_id)
    client.put(
        f"/api/papers/{paper_id}/notes/edit",
        json={"language": LANG, "markdown": "中文批注"},
    )

    other = client.get(f"/api/papers/{paper_id}/notes/state?language=en").json()
    assert other["edited"] is None


# --- versions -----------------------------------------------------------------

def test_an_older_version_can_be_brought_back(client, paper_id):
    seed_draft(paper_id)
    seed_history(
        paper_id,
        [
            {"at": "2026-01-01 10:00:00", "scope": "full", "source": "ai",
             "markdown": "# 旧版本", "evidence": []},
            {"at": "2025-12-01 10:00:00", "scope": "section:Introduction",
             "source": "edited", "markdown": "# 更早的版本", "evidence": []},
        ],
    )

    resp = client.post(
        f"/api/papers/{paper_id}/notes/restore",
        json={"language": LANG, "index": 1},
    )
    assert resp.status_code == 200, resp.text

    now = state(client, paper_id)
    assert now["edited"] == "# 更早的版本"
    assert now["markdown"] == DRAFT  # restored as an edit, not as the draft
    assert now["history"][1]["scope"] == "section:Introduction"


def test_restoring_a_version_that_does_not_exist_is_404(client, paper_id):
    seed_history(paper_id, [{"at": "x", "scope": "full", "source": "ai", "markdown": "v"}])
    resp = client.post(
        f"/api/papers/{paper_id}/notes/restore", json={"language": LANG, "index": 4}
    )
    assert resp.status_code == 404, resp.text
    assert state(client, paper_id)["edited"] is None


def test_history_records_where_a_version_came_from(client, paper_id):
    """The reader has to be able to tell a draft from their own old text."""
    seed_draft(paper_id)
    seed_history(
        paper_id,
        [{"at": "x", "scope": "section:方法", "source": "edited",
          "markdown": "m", "evidence": EVIDENCE}],
    )
    assert state(client, paper_id)["history"][0] == {
        "at": "x",
        "scope": "section:方法",
        "source": "edited",
        "markdown": "m",
        "evidence": EVIDENCE,
    }


# --- a failed generation is not a note ----------------------------------------

def test_a_failed_generation_leaves_the_reader_their_text(client, paper_id):
    """No provider is configured in the test run, so the call must fail — and
    failure must not present itself as a note."""
    seed_draft(paper_id)
    client.put(
        f"/api/papers/{paper_id}/notes/edit",
        json={"language": LANG, "markdown": "我的笔记"},
    )

    resp = client.post(
        f"/api/papers/{paper_id}/notes",
        json={"language": LANG, "refresh": True, "scope": "full"},
    )
    assert resp.status_code == 502, resp.text

    now = state(client, paper_id)
    assert now["edited"] == "我的笔记"
    assert now["markdown"] == DRAFT
    # And it is not filed as a version either: nothing happened, so there is
    # nothing to come back to.
    assert now["history"] == []


# --- printed page numbers -----------------------------------------------------

def _pages(client, paper_id: str) -> dict:
    resp = client.get(f"/api/papers/{paper_id}/pages")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_pages_carry_a_label_slot_for_every_page(client, paper_id, pdf_meta):
    pages = _pages(client, paper_id)
    assert len(pages["page_labels"]) == pdf_meta["n_pages"]
    # The sample PDF declares no page labels, so the UI falls back to position.
    assert all(not label for label in pages["page_labels"])


def test_a_pdf_that_numbers_its_pages_reports_those_numbers(client, pdf_bytes):
    """A journal renumbers a paper 1..n inside a longer file: the number printed
    on the page is not the position of the page in the file."""
    import fitz

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    doc.set_page_labels([{"startpage": 0, "prefix": "", "style": "D", "firstpagenum": 11}])
    data = doc.tobytes()
    doc.close()

    resp = client.post(
        "/api/papers/upload", files={"file": ("labelled.pdf", data, "application/pdf")}
    )
    assert resp.status_code == 200, resp.text
    pid = resp.json()["id"]
    try:
        assert _pages(client, pid)["page_labels"] == ["11", "12"]
    finally:
        client.delete(f"/api/papers/{pid}")


# --- writing evidence into the copy, not the linked original ------------------

def _write(client, paper_id: str, target: str) -> dict:
    resp = client.post(
        f"/api/papers/{paper_id}/evidence/pdf",
        json={"evidence": EVIDENCE, "target": target, "side": "original"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _evidence_marks(data: bytes) -> list[dict]:
    return [f for f in annot_facts(data) if f["title"] == "Gloss Evidence"]


def test_copy_target_writes_gloss_copy_and_spares_the_original(client, pdf_bytes):
    """The default: the reader's linked PDF is left exactly as it was."""
    resp = client.post(
        "/api/papers/upload", files={"file": ("paper.pdf", pdf_bytes, "application/pdf")}
    )
    pid = resp.json()["id"]
    try:
        outside = store.pdf_path(pid).with_name("outside-original.pdf")
        outside.write_bytes(pdf_bytes)
        store.set_paper_source_pdf(pid, str(outside))

        out = _write(client, pid, "copy")
        assert out["written"] == 1, out

        assert len(_evidence_marks(served_pdf(client, pid))) == 1
        assert _evidence_marks(outside.read_bytes()) == []
    finally:
        client.delete(f"/api/papers/{pid}")
