"""Study notes: a polished, faithful structured Markdown note for a paper.

The note ships with an evidence trail: key claims are tagged ``[E1]``, ``[E2]``…
and every tag resolves to a sentence copied verbatim from the paper that we have
located in the PDF, so the reader can jump from a claim straight to the original.

Two things are deliberately kept apart from the generated note:

* the reader's own edit (``notes_edit:<lang>``), so a regeneration never silently
  discards hand-written work — the previous content moves into
  ``notes_history:<lang>`` first;
* the scope of a regeneration (whole paper or one section), so "regenerate this
  section" does not rebuild — and re-word — the whole note.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from ..config import output_language
from ..library import store
from ..pdf import ingest
from ..pdf import structure
from .common import json_complete, truncate_to_tokens

#: Cap on tagged quotes, so a long note can't spend forever probing the PDF.
MAX_EVIDENCE = 12

#: Below this, a string is too short to search a paper for: it matches all over
#: the place, and a mark put on the first of those would be a lie about where
#: the claim came from. Such a quote is kept with ``page=None`` rather than
#: dropped — dropping it would leave its [E3] marker pointing at nothing.
MIN_QUOTE = 12

#: How many previous versions of a note to keep. Enough to undo a bad
#: regeneration, small enough that the cache stays a cache.
MAX_HISTORY = 6

#: Tokens of source text handed to the model, per scope.
FULL_TEXT_TOKENS = 60000
SECTION_TEXT_TOKENS = 24000

SYSTEM = (
    "You are Gloss, an expert researcher writing polished, faithful study "
    "notes for an academic paper. Be concrete; never hallucinate; only use the "
    "paper. Cite section/figure names when useful, and render math with $...$. "
    "Write ENTIRELY in {lang}. Use Markdown with clear ## headings in this order: "
    "一句话概述 / 背景与动机 / 要解决的问题 / 核心方法(附直觉解释) / 关键公式与符号 / "
    "实验设置 / 主要结果(含关键数字) / 创新点 / 局限与不足 / 对我的启发(可复用点) / "
    "待深入的问题. (Translate these heading names into {lang} if {lang} is not Chinese.)"
    "\n\n=== PROVENANCE TAGS (required) ===\n"
    "Every factual sentence ends with one provenance tag, so the reader always "
    "knows what they are looking at:\n"
    "- `[原文]` — stated in the paper. Follow it with an evidence marker, e.g. "
    "``[原文][E3]``.\n"
    "- `[AI 解读]` — your own synthesis, inference or reading between the lines. "
    "Never attach an evidence marker to it.\n"
    "- `[待核实]` — plausible but not actually shown in the paper: an unstated "
    "assumption, a number you cannot find, something the paper only implies. "
    "Say in one clause what would settle it.\n"
    "If {lang} is not Chinese, use `[source]`, `[AI reading]`, `[unverified]` "
    "instead, and keep them in that exact Latin form."
    "\n\n=== NUMBERS (required) ===\n"
    "A number without its conditions is not a result. For every quantitative "
    "claim give, in the same sentence: the metric, the dataset/benchmark or "
    "experimental condition, the baseline it is compared against, the direction "
    "of the change, and an evidence marker. Write the paper's own number and do "
    "not recompute it. Distinguish a percentage (%, a relative change) from a "
    "percentage point (pp, an absolute difference) and name the one the paper "
    "used; if the paper does not say which, write `[待核实]` after it."
    "\n\n=== OUTSIDE KNOWLEDGE ===\n"
    "Background knowledge that is not in this paper goes into a final section "
    "titled `## 外部补充（非本文内容）` (`## Outside context (not from this "
    "paper)` if {lang} is not Chinese) and nowhere else. Prefix every item in it "
    "with `[外部]` so it can never be mistaken for a claim of the paper. If you "
    "have nothing outside to add, say so in one line — do not pad it."
    "\n\n=== EVIDENCE TAGS ===\n"
    "After every `[原文]` claim, method step, or number, put a marker like [E1], "
    "[E2]… numbered in order of first appearance. Then list each marker under "
    '"evidence" with:\n'
    '- "id": the marker, e.g. "E1".\n'
    '- "quote": the sentence copied VERBATIM from the paper, in the paper\'s own '
    "language. We search the PDF for this exact string to locate it, so it must "
    "be a single real sentence from the paper — never paraphrased, never "
    "translated, never trimmed mid-word.\n"
    '- "why": one short note in {lang} saying why it matters.\n'
    "Use at most {max_evidence} markers, and only for claims worth revisiting."
)

SHAPE = (
    '{"markdown": "...", "evidence": [{"id": "E1", '
    '"quote": "<verbatim sentence from the paper>", "why": "<why it matters>"}]}'
)


def notes_state(paper_id: str, language: str | None = None) -> dict:
    """The note as the UI should see it: draft, reader edit, version history.

    ``markdown``/``evidence`` are what the model produced; ``edited`` is what the
    reader typed over it (``null`` while they have not touched it); ``history``
    holds older versions kept when a regeneration replaced them.
    """
    lang = language or output_language()
    cached = store.cache_get(paper_id, f"notes2:{lang}")
    # Notes cached before evidence existed were a bare markdown string.
    if isinstance(cached, str):
        cached = {"markdown": cached, "evidence": []}
    if not isinstance(cached, dict):
        cached = {}
    edited = store.cache_get(paper_id, f"notes_edit:{lang}")
    raw_history = store.cache_get(paper_id, f"notes_history:{lang}")
    history: list[dict] = []
    if isinstance(raw_history, list):
        for item in raw_history:
            if not isinstance(item, dict):
                continue
            history.append({
                "at": str(item.get("at") or ""),
                "scope": str(item.get("scope") or ""),
                "source": str(item.get("source") or "ai"),
                "markdown": str(item.get("markdown") or ""),
                "evidence": item.get("evidence") or [],
            })
    return {
        "markdown": str(cached.get("markdown") or ""),
        "evidence": cached.get("evidence") or [],
        "edited": edited if isinstance(edited, str) else None,
        "history": history,
        "language": lang,
    }


def save_edit(paper_id: str, markdown: str, language: str | None = None) -> dict:
    """Store the reader's own version of the note. Never touches the AI draft."""
    lang = language or output_language()
    store.cache_set(paper_id, f"notes_edit:{lang}", markdown)
    return notes_state(paper_id, lang)


def revert_edit(paper_id: str, language: str | None = None) -> dict:
    """Drop the reader's edit and show the AI draft again (draft is preserved)."""
    lang = language or output_language()
    # No DELETE helper in the store; a null value reads back as "no edit".
    store.cache_set(paper_id, f"notes_edit:{lang}", None)
    return notes_state(paper_id, lang)


def restore_version(paper_id: str, index: int, language: str | None = None) -> dict:
    """Bring back a version from the history as the current reader edit."""
    lang = language or output_language()
    state = notes_state(paper_id, lang)
    if index < 0 or index >= len(state["history"]):
        raise IndexError("no such note version")
    version = state["history"][index]
    store.cache_set(paper_id, f"notes_edit:{lang}", version["markdown"])
    return notes_state(paper_id, lang)


def _push_history(paper_id: str, lang: str, state: dict, scope_label: str) -> None:
    """Archive what the reader is looking at before it gets replaced."""
    current = state.get("edited")
    if current is None:
        current = state.get("markdown") or ""
    if not current.strip():
        return
    entry = {
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "scope": scope_label,
        "source": "edited" if state.get("edited") is not None else "ai",
        "markdown": current,
        "evidence": state.get("evidence") or [],
    }
    raw = store.cache_get(paper_id, f"notes_history:{lang}")
    history = [h for h in raw if isinstance(h, dict)] if isinstance(raw, list) else []
    # Never archive the same text twice in a row: repeated failed regenerations
    # would otherwise push the real old version out of the window.
    if history and history[0].get("markdown") == entry["markdown"]:
        return
    history.insert(0, entry)
    store.cache_set(paper_id, f"notes_history:{lang}", history[:MAX_HISTORY])


def _flat_blocks(parsed: dict) -> list[dict]:
    """Every text block in reading order, tagged with the page it came from."""
    out: list[dict] = []
    for page in parsed.get("pages") or []:
        for block in page.get("blocks") or []:
            if block.get("text"):
                out.append({
                    "page": page.get("index"),
                    "block_id": block.get("id"),
                    "text": block["text"],
                })
    return out


def section_text(parsed: dict, title: str) -> tuple[str, int | None]:
    """The text of one section: its heading through the line before the next.

    Returns ``(text, start_page)``. A title we cannot find yields empty text,
    and the caller falls back to the whole paper rather than inventing a range.
    """
    sections = structure.detect_sections(parsed)
    blocks = _flat_blocks(parsed)
    if not sections or not blocks:
        return "", None

    target = (title or "").strip().lower()
    if not target:
        return "", None

    def position(section: dict) -> int | None:
        block_id = section.get("block_id")
        if block_id is not None:
            for i, block in enumerate(blocks):
                if block["block_id"] == block_id:
                    return i
        page = section.get("page")
        if page is None:
            return None
        for i, block in enumerate(blocks):
            if block["page"] == page:
                return i
        return None

    starts: list[int | None] = [position(s) for s in sections]
    hit = -1
    for i, section in enumerate(sections):
        if str(section.get("title") or "").strip().lower() == target:
            hit = i
            break
    if hit < 0:
        return "", None

    start = starts[hit]
    if start is None:
        return "", None
    level = int(sections[hit].get("level") or 1)
    end = len(blocks)
    for j in range(hit + 1, len(sections)):
        nxt = starts[j]
        if nxt is None or nxt <= start:
            continue
        if int(sections[j].get("level") or 1) <= level:
            end = nxt
            break
    text = "\n\n".join(b["text"] for b in blocks[start:end])
    return text, blocks[start]["page"]


def _scope_source(
    parsed: dict, *, scope: str | None, section: str | None,
) -> tuple[str, str]:
    """Pick the text a regeneration reads, and a label for the history entry."""
    if scope == "section" and section:
        text, _ = section_text(parsed, section)
        if text.strip():
            return truncate_to_tokens(text, SECTION_TEXT_TOKENS), f"section:{section}"
        # An unlocatable section is worse than the whole paper: say nothing,
        # read everything, and let the label record what was asked for.
        return truncate_to_tokens(parsed["full_text"], FULL_TEXT_TOKENS), f"section:{section}"
    return truncate_to_tokens(parsed["full_text"], FULL_TEXT_TOKENS), "full"


async def build_notes(
    paper_id: str, *, language: str | None = None, refresh: bool = False,
    provider: str | None = None, model: str | None = None,
    scope: str | None = None, section: str | None = None,
) -> dict:
    """Structured note plus the located quotes it references.

    Returns the full :func:`notes_state` shape so the caller sees the draft, any
    reader edit and the history in one place.
    """
    lang = language or output_language()
    if not refresh:
        cached = store.cache_get(paper_id, f"notes2:{lang}")
        if cached:
            return notes_state(paper_id, lang)

    parsed = store.load_parsed(paper_id)
    if not parsed:
        raise ValueError("paper not parsed")

    # What the reader is looking at right now, kept aside until the new draft is
    # in hand: a generation that fails must leave absolutely nothing behind.
    before = notes_state(paper_id, lang)

    text, scope_label = _scope_source(parsed, scope=scope, section=section)
    system = SYSTEM.format(lang=lang, max_evidence=MAX_EVIDENCE)
    if scope_label.startswith("section:"):
        user = (
            f"Write structured study notes for the section \"{section}\" of this "
            f"paper, in {lang}. Stay inside that section; do not summarise the "
            f"whole paper. Tag each key claim with a provenance tag and an "
            f"evidence marker, and give the verbatim sentence it comes from."
            f"\n\n=== SECTION ===\n{text}"
        )
    else:
        user = (
            f"Write structured study notes for this paper, in {lang}.\n"
            f"Tag each key claim with a provenance tag and an evidence marker, "
            f"and give the verbatim sentence it comes from.\n\n=== PAPER ===\n{text}"
        )
    result = await json_complete(system, user, SHAPE, provider=provider, model=model)
    out = {
        "markdown": (result.get("markdown") or "").strip(),
        "evidence": await _locate_evidence(paper_id, result.get("evidence") or []),
        "scope": scope_label,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    # Only now is anything replaced: the draft is archived first, so a
    # regeneration is never a silent overwrite of the reader's own text.
    _push_history(paper_id, lang, before, scope_label)
    store.cache_set(paper_id, f"notes2:{lang}", out)
    return notes_state(paper_id, lang)


async def _locate_evidence(paper_id: str, items: list) -> list[dict]:
    """Resolve every quote to a page + rectangles so the UI can jump to it.

    A quote that can't be found stays in the list with ``page=None`` — dropping
    it would leave a dead [E3] marker in the prose.
    """
    pdf = store.pdf_path(paper_id)
    out: list[dict] = []
    for item in items[:MAX_EVIDENCE]:
        if not isinstance(item, dict):
            continue
        quote = " ".join(str(item.get("quote") or "").split())
        loc = None
        if len(quote) >= MIN_QUOTE:
            loc = await asyncio.to_thread(ingest.locate_text, pdf, quote)
        out.append({
            "id": str(item.get("id") or f"E{len(out) + 1}").strip(),
            "quote": quote,
            "why": str(item.get("why") or ""),
            "page": loc["page"] if loc else None,
            "rects": loc["rects"] if loc else [],
            "exact": bool(loc and loc.get("exact")),
        })
    return out
