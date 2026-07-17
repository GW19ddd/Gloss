"""Context-aware translation.

- `translate_text`: translate an ad-hoc selection.
- Sentence-level page/range translation with a PERSISTENT per-sentence cache
  (SQLite, survives restarts). Sentences are keyed by a content hash, so a
  sentence already translated on page 3 is reused for free when you later
  translate pages 3-5. `get_translations` returns everything already translated
  (in document order) so the UI can restore state on re-entry.
"""
from __future__ import annotations

import hashlib

from ..config import load_config
from ..library import store
from ..pdf import structure
from .common import json_complete, text_complete

SYSTEM = (
    "You are Gloss's academic translator. Translate faithfully into {target}, "
    "preserving technical terminology, entity names, and inline math/LaTeX EXACTLY "
    "as written (do not translate symbols inside $...$). Keep the meaning precise; "
    "do not add or drop content. Output only the translation."
)

MAX_RANGE_PAGES = 15
_BATCH = 40  # sentences per LLM call


def _target(language: str | None) -> str:
    return language or load_config().get("target_language", "中文 (Simplified Chinese)")


def _sid(text: str) -> str:
    return hashlib.md5(" ".join(text.split()).lower().encode()).hexdigest()[:16]


def _cache_key(target: str) -> str:
    return f"senttrans:{target}"


def paper_sentences(parsed: dict) -> list[dict]:
    """Ordered sentences across the paper: {page, sid, original}."""
    out: list[dict] = []
    for page in parsed.get("pages", []):
        for b in page.get("blocks", []):
            for s in structure.split_sentences(b.get("text", "")):
                out.append({"page": page["index"], "sid": _sid(s), "original": s})
    return out


async def translate_text(
    text: str, *, language: str | None = None, provider: str | None = None, model: str | None = None
) -> str:
    tgt = _target(language)
    return await text_complete(SYSTEM.format(target=tgt), text, provider=provider, model=model)


async def translate_range(
    paper_id: str, start: int, end: int, *, language: str | None = None,
    provider: str | None = None, model: str | None = None,
) -> list[dict]:
    """Translate sentences on pages [start, end] (0-based). Reuses cached sentences."""
    parsed = store.load_parsed(paper_id)
    if not parsed:
        raise ValueError("paper not parsed")
    n = parsed["n_pages"]
    start = max(0, min(start, n - 1))
    end = max(start, min(end, n - 1))
    if end - start + 1 > MAX_RANGE_PAGES:
        raise ValueError(f"range too large — translate at most {MAX_RANGE_PAGES} pages at once")

    tgt = _target(language)
    sents = [s for s in paper_sentences(parsed) if start <= s["page"] <= end]
    cache = store.cache_get(paper_id, _cache_key(tgt)) or {}

    # collect sentences that still need translating (unique by sid)
    todo: dict[str, str] = {}
    for s in sents:
        if not cache.get(s["sid"]):
            todo.setdefault(s["sid"], s["original"])

    if todo:
        items = list(todo.items())  # [(sid, text)]
        system = (
            SYSTEM.format(target=tgt)
            + " You are given numbered sentences; translate EACH and return by index."
        )
        shape = '{"s": [{"i": 0, "t": "translation"}, ...]}'
        for i in range(0, len(items), _BATCH):
            chunk = items[i : i + _BATCH]
            numbered = "\n".join(f"[{j}] {t}" for j, (_sid_, t) in enumerate(chunk))
            result = await json_complete(system, numbered, shape, provider=provider, model=model)
            by_i = {int(x["i"]): x.get("t", "") for x in result.get("s", []) if "i" in x}
            for j, (sid, _t) in enumerate(chunk):
                cache[sid] = by_i.get(j, "")
        store.cache_set(paper_id, _cache_key(tgt), cache)

    return [
        {"page": s["page"], "original": s["original"], "translation": cache.get(s["sid"], "")}
        for s in sents
    ]


async def translate_page(
    paper_id: str, page: int, *, language: str | None = None,
    provider: str | None = None, model: str | None = None,
) -> list[dict]:
    return await translate_range(paper_id, page, page, language=language, provider=provider, model=model)


def get_translations(paper_id: str, *, language: str | None = None) -> list[dict]:
    """Return every already-translated sentence (document order) for restore-on-entry."""
    parsed = store.load_parsed(paper_id)
    if not parsed:
        return []
    tgt = _target(language)
    cache = store.cache_get(paper_id, _cache_key(tgt)) or {}
    out = []
    for s in paper_sentences(parsed):
        t = cache.get(s["sid"])
        if t:
            out.append({"page": s["page"], "original": s["original"], "translation": t})
    return out


def translated_pages(paper_id: str, *, language: str | None = None) -> list[int]:
    """Pages that have at least one translated sentence."""
    return sorted({s["page"] for s in get_translations(paper_id, language=language)})
