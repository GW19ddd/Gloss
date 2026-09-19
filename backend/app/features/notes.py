"""Study notes: a polished, faithful structured Markdown note for a paper.

The note ships with an evidence trail: key claims are tagged ``[E1]``, ``[E2]``…
and every tag resolves to a sentence copied verbatim from the paper that we have
located in the PDF, so the reader can jump from a claim straight to the original.
"""
from __future__ import annotations

import asyncio

from ..config import output_language
from ..library import store
from ..pdf import ingest
from .common import json_complete, truncate_to_tokens

#: Cap on tagged quotes, so a long note can't spend forever probing the PDF.
MAX_EVIDENCE = 12

SYSTEM = (
    "You are Gloss, an expert researcher writing polished, faithful study "
    "notes for an academic paper. Be concrete; never hallucinate; only use the "
    "paper. Cite section/figure names when useful, and render math with $...$. "
    "Write ENTIRELY in {lang}. Use Markdown with clear ## headings in this order: "
    "一句话概述 / 背景与动机 / 要解决的问题 / 核心方法(附直觉解释) / 关键公式与符号 / "
    "实验设置 / 主要结果(含关键数字) / 创新点 / 局限与不足 / 对我的启发(可复用点) / "
    "待深入的问题. (Translate these heading names into {lang} if {lang} is not Chinese.)"
    "\n\n=== EVIDENCE TAGS ===\n"
    "After every key claim, method step, or number, put a marker like [E1], "
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


async def build_notes(
    paper_id: str, *, language: str | None = None, refresh: bool = False,
    provider: str | None = None, model: str | None = None,
) -> dict:
    """Structured note plus the located quotes it references.

    Returns ``{"markdown": str, "evidence": [{id, quote, why, page, rects}]}``.
    """
    lang = language or output_language()
    cache_key = f"notes2:{lang}"
    if not refresh:
        cached = store.cache_get(paper_id, cache_key)
        if cached:
            # Notes cached before evidence existed were a bare string.
            if isinstance(cached, dict):
                return cached
            return {"markdown": cached, "evidence": []}

    parsed = store.load_parsed(paper_id)
    if not parsed:
        raise ValueError("paper not parsed")
    text = truncate_to_tokens(parsed["full_text"], 60000)
    system = SYSTEM.format(lang=lang, max_evidence=MAX_EVIDENCE)
    user = (
        f"Write structured study notes for this paper, in {lang}.\n"
        f"Tag each key claim with an evidence marker and give the verbatim "
        f"sentence it comes from.\n\n=== PAPER ===\n{text}"
    )
    result = await json_complete(system, user, SHAPE, provider=provider, model=model)
    out = {
        "markdown": (result.get("markdown") or "").strip(),
        "evidence": await _locate_evidence(paper_id, result.get("evidence") or []),
    }
    store.cache_set(paper_id, cache_key, out)
    return out


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
        if len(quote) < 12:
            continue
        loc = await asyncio.to_thread(ingest.locate_text, pdf, quote)
        out.append({
            "id": str(item.get("id") or f"E{len(out) + 1}").strip(),
            "quote": quote,
            "why": str(item.get("why") or ""),
            "page": loc["page"] if loc else None,
            "rects": loc["rects"] if loc else [],
        })
    return out
