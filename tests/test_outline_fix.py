"""The AI outline-fix feature: cache override on /pages + reset endpoint."""
from __future__ import annotations

from app.features.outline import is_noisy
from app.library import store


def _sec(title: str, page: int = 0) -> dict:
    return {"title": title, "page": page, "block_id": None, "level": 1}


def test_is_noisy_detection():
    clean = [_sec(f"{i}. Section {i}", i) for i in range(1, 6)]
    assert not is_noisy(clean)

    messy = clean + [_sec("status ← Runner(□□-1)", 1) for _ in range(3)]
    assert is_noisy(messy)

    duplicated = clean + [_sec("2. Methods", 2) for _ in range(3)]
    assert is_noisy(duplicated)

    # too few entries to judge — leave it alone
    assert not is_noisy(clean[:3])


def test_fixed_outline_overrides_pages(client, paper_id):
    original = client.get(f"/api/papers/{paper_id}/pages").json()
    assert original["outline_fixed"] is False
    assert original["sections"], "sample PDF must produce some outline entries"

    fake = [{"title": "1. Introduction", "page": 0, "block_id": None, "level": 1}]
    store.cache_set(paper_id, "fixed_outline", fake)

    fixed = client.get(f"/api/papers/{paper_id}/pages").json()
    assert fixed["outline_fixed"] is True
    assert fixed["sections"] == fake


def test_reset_outline_restores_heuristic(client, paper_id):
    store.cache_set(
        paper_id, "fixed_outline",
        [{"title": "bogus", "page": 0, "block_id": None, "level": 1}],
    )
    resp = client.post(f"/api/papers/{paper_id}/reset_outline")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sections"][0]["title"] != "bogus"

    pages = client.get(f"/api/papers/{paper_id}/pages").json()
    assert pages["outline_fixed"] is False
    assert pages["sections"] == body["sections"]


ZH = "中文 (Simplified Chinese)"
EN = "English"


def _pages(client, paper_id, language=None):
    query = f"?language={language}" if language else ""
    return client.get(f"/api/papers/{paper_id}/pages{query}").json()


def test_outline_is_cached_per_language(client, paper_id):
    zh = [{"title": "1. 引言", "page": 0, "block_id": None, "level": 1}]
    en = [{"title": "1. Introduction", "page": 0, "block_id": None, "level": 1}]
    store.cache_set(paper_id, "fixed_outline:zh", zh)
    store.cache_set(paper_id, "fixed_outline:en", en)

    zh_pages = _pages(client, paper_id, ZH)
    en_pages = _pages(client, paper_id, EN)
    assert zh_pages["outline_language"] == "zh"
    assert zh_pages["sections"] == zh
    assert en_pages["outline_language"] == "en"
    assert en_pages["sections"] == en


def test_reset_outline_only_clears_one_language(client, paper_id):
    en = [{"title": "1. Introduction", "page": 0, "block_id": None, "level": 1}]
    store.cache_set(paper_id, "fixed_outline:zh", [{"title": "1. 引言", "page": 0, "level": 1}])
    store.cache_set(paper_id, "fixed_outline:en", en)

    resp = client.post(f"/api/papers/{paper_id}/reset_outline?language={ZH}")
    assert resp.status_code == 200
    assert _pages(client, paper_id, ZH)["outline_fixed"] is False
    assert _pages(client, paper_id, EN)["sections"] == en


def test_legacy_outline_still_applies_and_resets(client, paper_id):
    fake = [{"title": "1. Introduction", "page": 0, "block_id": None, "level": 1}]
    store.cache_set(paper_id, "fixed_outline", fake)
    assert _pages(client, paper_id, ZH)["sections"] == fake

    # the pre-language key must not resurrect the outline after a reset
    client.post(f"/api/papers/{paper_id}/reset_outline?language={ZH}")
    assert _pages(client, paper_id, ZH)["outline_fixed"] is False


def test_write_outline_into_pdf_and_restore(client, paper_id):
    sections = [
        {"title": "1. 引言", "page": 0, "block_id": None, "level": 1},
        {"title": "2. 方法", "page": 1, "block_id": None, "level": 2},
    ]
    store.cache_set(paper_id, "fixed_outline:zh", sections)

    resp = client.post(
        f"/api/papers/{paper_id}/outline/to-pdf", json={"language": ZH}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"written": 2, "language": "zh"}

    # the bookmarks are really in the file now, not just in the database
    assert [entry[1] for entry in _pdf_toc(paper_id)] == ["1. 引言", "2. 方法"]
    assert _pages(client, paper_id, ZH)["outline_written"] is True

    # ...and the bookmarks the PDF had (none, here) can be put back
    resp = client.post(f"/api/papers/{paper_id}/outline/restore-pdf")
    assert resp.status_code == 200, resp.text
    assert _pdf_toc(paper_id) == []
    assert _pages(client, paper_id, ZH)["outline_written"] is False


def _pdf_toc(paper_id: str) -> list:
    import fitz

    from app.pdf.annot_writer import target_path

    with fitz.open(str(target_path(paper_id))) as doc:
        return doc.get_toc(simple=True)
