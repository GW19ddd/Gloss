"""AI cleanup for a messy extracted outline.

The PDF bookmark / heading heuristics often produce noise: formula fragments,
repeated sub-sections, broken hierarchy. One LLM pass rewrites the outline —
dedupe, drop non-heading lines, normalize levels — while keeping the original
page mapping, so every entry still jumps to the right page.
"""
from __future__ import annotations

import re
from collections import Counter

from ..config import output_language
from ..library import store
from ..pdf import outline_writer, structure
from .common import json_complete


def lang_key(language: str | None = None) -> str:
    """Collapse the free-form output-language setting to ``"zh"`` / ``"en"``.

    The outline is either all Chinese or all English, so only these two buckets
    exist. Same rule the client uses to tell Chinese answers from English ones.
    """
    return "zh" if (language or output_language()).startswith("中文") else "en"


def cache_key(lang: str) -> str:
    return f"{CACHE_KEY}:{lang}"

#: Pre-language cache key. Still read (see ``get_outline``) so an outline fixed
#: before outlines became language-aware survives the upgrade untouched.
CACHE_KEY = "fixed_outline"
#: The PDF's own bookmarks as they were before Gloss overwrote them, kept so the
#: write can be undone.
ORIGINAL_TOC_KEY = "original_toc"
#: Whether the PDF's bookmarks currently hold a Gloss outline.
PDF_WRITTEN_KEY = "outline_in_pdf"

SYSTEM = (
    "You clean up a paper's table of contents that was extracted (noisily) from "
    "a PDF. Keep every entry that is a real section heading; drop lines that are "
    "obviously not headings (formula fragments, author lists, page furniture, "
    "citation leftovers, stray letters like 'a)'). Merge duplicates that were "
    "extracted twice. Fix the hierarchy level (1 = chapter, 2 = section, 3 = "
    "subsection). Never invent sections that are not in the input."
)

#: Appended to the system prompt: the outline is written in one language only.
LANGUAGE_RULE = {
    "zh": (
        "Write EVERY title in Simplified Chinese, translating the ones that are "
        "not already Chinese. Keep the original numbering prefix (e.g. '3.2 方法'). "
        "Keep established English terms — model names, dataset names, acronyms "
        "(Transformer, GPT, ImageNet) — as they are. Reply with Chinese titles only."
    ),
    "en": (
        "Write EVERY title in English, translating the ones that are not already "
        "English. Keep the original numbering prefix (e.g. '3.2 Method'). Reply "
        "with English titles only."
    ),
}

SHAPE = ('{"sections": [{"i": "<index of the input line this entry came from>", '
         '"title": "<cleaned title>", "level": <1..3>}]}')


def _detect(paper_id: str) -> list[dict]:
    parsed = store.load_parsed(paper_id)
    if not parsed:
        raise ValueError("paper not parsed")
    return structure.detect_sections(parsed)


# Titles that carry math glyphs, template placeholders, identifier-style
# fragments, or stray list letters are extraction noise, not headings.
_NOISE_RE = re.compile(
    r"[←→⇐⇒=≠≈≤≥±Δ∂∇⊗⊕∈⊂∩√∫µ]"
    r"|[{}<>|]"
    r"|\w+_\{?\w"
    r"|^\s*[a-z0-9]\)\s*$"
)


def is_noisy(sections: list[dict]) -> bool:
    """Cheap offline check: does the extracted outline look broken enough
    that an AI cleanup is worth a round-trip?"""
    if len(sections) < 4:
        return False
    titles = [s.get("title", "") for s in sections]
    noisy = sum(1 for t in titles if _NOISE_RE.search(t))
    if noisy >= 3 and noisy / len(titles) >= 0.06:
        return True
    # the same heading extracted three or more times is never right
    dup = Counter(t.strip().lower() for t in titles)
    return dup.most_common(1)[0][1] >= 3


async def fix_outline(
    paper_id: str, *, language: str | None = None, refresh: bool = False,
    provider: str | None = None, model: str | None = None,
) -> list[dict]:
    """Run the AI cleanup in ``language`` and cache it (it overrides /pages).

    Each language is cached on its own key, so switching the answer language
    shows that language's outline instead of re-translating every time.
    """
    sections = _detect(paper_id)
    if not sections:
        raise ValueError("no outline entries to fix")
    lang = lang_key(language)
    if not refresh:
        cached = store.cache_get(paper_id, cache_key(lang))
        if cached:
            return cached

    numbered = "\n".join(
        f"{i}. [level {s['level']}, page {s['page'] + 1}] {s['title']}"
        for i, s in enumerate(sections)
    )
    user = (
        f"Clean up this extracted outline of an academic paper. Reply with the "
        f"input index `i` for every kept entry so pages can be re-attached.\n\n"
        f"=== EXTRACTED OUTLINE ===\n{numbered}"
    )
    system = f"{SYSTEM} {LANGUAGE_RULE[lang]}"
    result = await json_complete(system, user, SHAPE, provider=provider, model=model)
    items = result.get("sections") or []

    cleaned: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for item in items:
        try:
            idx = int(item["i"])
        except (KeyError, TypeError, ValueError):
            continue
        if not 0 <= idx < len(sections):
            continue
        title = str(item.get("title") or sections[idx]["title"]).strip()[:120]
        if not title:
            continue
        try:
            level = max(1, min(6, int(item.get("level", sections[idx]["level"]))))
        except (TypeError, ValueError):
            level = sections[idx]["level"]
        src = sections[idx]
        key = (title.lower(), src["page"])
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({
            "title": title,
            "page": src["page"],
            "block_id": src.get("block_id"),
            "level": level,
        })
    if not cleaned:
        raise ValueError("AI returned an empty outline; nothing changed")
    store.cache_set(paper_id, cache_key(lang), cleaned)
    return cleaned


def get_outline(
    paper_id: str, language: str | None = None, *, sections: list[dict] | None = None
) -> dict:
    """The outline in effect: the AI version for ``language`` if there is one,
    otherwise the raw extraction (``sections`` saves a re-detect)."""
    lang = lang_key(language)
    fixed = store.cache_get(paper_id, cache_key(lang))
    if not fixed:
        # an outline fixed before outlines became language-aware is treated as
        # this language's version rather than thrown away
        fixed = store.cache_get(paper_id, CACHE_KEY)
    return {
        "sections": fixed or sections or _detect(paper_id),
        "fixed": bool(fixed),
        "language": lang,
    }


def reset_outline(paper_id: str, language: str | None = None) -> list[dict]:
    """Drop the AI-fixed outline of one language; back to the raw extraction."""
    store.cache_set(paper_id, cache_key(lang_key(language)), None)
    # the pre-language key would otherwise resurrect the outline on every read
    store.cache_set(paper_id, CACHE_KEY, None)
    return _detect(paper_id)


def write_to_pdf(paper_id: str, *, language: str | None = None) -> dict:
    """Make the current outline the PDF's own bookmarks.

    Whatever bookmarks the file had are snapshotted first (once), so
    ``restore_pdf`` can put them back. Returns how many entries were written.
    """
    sections = get_outline(paper_id, language)["sections"]
    if not sections:
        raise ValueError("no outline to write")
    if store.cache_get(paper_id, ORIGINAL_TOC_KEY) is None:
        store.cache_set(paper_id, ORIGINAL_TOC_KEY, outline_writer.read_toc(paper_id) or [])
    written = outline_writer.write_toc(paper_id, sections)
    store.cache_set(paper_id, PDF_WRITTEN_KEY, True)
    return {"written": written, "language": lang_key(language)}


def restore_pdf(paper_id: str) -> dict:
    """Put the bookmarks the PDF had before Gloss overwrote them back."""
    original = store.cache_get(paper_id, ORIGINAL_TOC_KEY)
    if original is None:
        raise ValueError("this paper has no saved bookmarks to restore")
    if not original:
        # the PDF had no bookmarks at all, so restoring means having none again
        outline_writer.clear_toc(paper_id)
        restored = 0
    else:
        entries = [
            {"level": item[0], "title": item[1], "page": max(0, int(item[2]) - 1)}
            for item in original if len(item) >= 3
        ]
        restored = outline_writer.write_toc(paper_id, entries)
    store.cache_set(paper_id, PDF_WRITTEN_KEY, False)
    return {"restored": restored}


def pdf_written(paper_id: str) -> bool:
    """Whether the PDF's bookmarks currently hold a Gloss outline."""
    return bool(store.cache_get(paper_id, PDF_WRITTEN_KEY))
