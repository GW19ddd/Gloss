"""Context-aware translation (selection, or a whole page for side-by-side view)."""
from __future__ import annotations

from ..config import load_config
from ..library import store
from .common import json_complete, text_complete

SYSTEM = (
    "You are Moonlight's academic translator. Translate faithfully into {target}, "
    "preserving technical terminology, entity names, and inline math/LaTeX EXACTLY "
    "as written (do not translate symbols inside $...$). Keep the meaning precise; "
    "do not add or drop content. Output only the translation."
)


def _target(language: str | None) -> str:
    return language or load_config().get("target_language", "中文 (Simplified Chinese)")


async def translate_text(
    text: str, *, language: str | None = None, provider: str | None = None, model: str | None = None
) -> str:
    tgt = _target(language)
    return await text_complete(
        SYSTEM.format(target=tgt), text, provider=provider, model=model
    )


async def translate_page(
    paper_id: str, page: int, *, language: str | None = None,
    provider: str | None = None, model: str | None = None,
) -> list[dict]:
    """Translate each text block on a page for a side-by-side overlay."""
    parsed = store.load_parsed(paper_id)
    if not parsed:
        raise ValueError("paper not parsed")
    if page < 0 or page >= parsed["n_pages"]:
        raise ValueError("page out of range")
    blocks = [b for b in parsed["pages"][page]["blocks"] if len(b["text"].strip()) > 1]
    tgt = _target(language)

    # cache per page+language
    cache_key = f"translate_page:{page}:{tgt}"
    cached = store.cache_get(paper_id, cache_key)
    if cached:
        return cached

    numbered = "\n\n".join(f"[{i}] {b['text']}" for i, b in enumerate(blocks))
    system = (
        SYSTEM.format(target=tgt)
        + " You are given numbered text blocks; translate EACH and return them by index."
    )
    shape = '{"blocks": [{"i": 0, "t": "translation"}, ...]}'
    result = await json_complete(system, numbered, shape, provider=provider, model=model)
    by_i = {int(x["i"]): x.get("t", "") for x in result.get("blocks", []) if "i" in x}

    out = []
    for i, b in enumerate(blocks):
        out.append({
            "page": page,
            "block_id": b["id"],
            "bbox": b["bbox"],
            "original": b["text"],
            "translation": by_i.get(i, ""),
        })
    store.cache_set(paper_id, cache_key, out)
    return out


MAX_RANGE_PAGES = 15


async def translate_range(
    paper_id: str, start: int, end: int, *, language: str | None = None,
    provider: str | None = None, model: str | None = None,
) -> list[dict]:
    """Translate every page in [start, end] (0-based inclusive), capped for cost."""
    parsed = store.load_parsed(paper_id)
    if not parsed:
        raise ValueError("paper not parsed")
    n = parsed["n_pages"]
    start = max(0, min(start, n - 1))
    end = max(start, min(end, n - 1))
    if end - start + 1 > MAX_RANGE_PAGES:
        raise ValueError(f"range too large — translate at most {MAX_RANGE_PAGES} pages at once")
    out: list[dict] = []
    for p in range(start, end + 1):
        out.extend(
            await translate_page(paper_id, p, language=language, provider=provider, model=model)
        )
    return out
