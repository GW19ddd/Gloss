"""Auto-highlight: LLM picks key sentences by category; anchor them to PDF rects."""
from __future__ import annotations

import asyncio

from ..config import output_language
from ..library import store
from ..pdf import annot_writer, ingest
from .common import json_complete, truncate_to_tokens

CATEGORY_COLORS = {
    "contribution": "#a5d6a7",   # green
    "method": "#90caf9",         # blue
    "result": "#fff59d",         # yellow
    "limitation": "#ef9a9a",     # red
    "definition": "#ce93d8",     # purple
    "background": "#ffcc80",     # orange
}

#: Chinese names the model sometimes returns; normalised back to the colour keys.
CATEGORY_ALIASES = {
    "贡献": "contribution",
    "方法": "method",
    "结果": "result",
    "局限": "limitation",
    "局限性": "limitation",
    "限制": "limitation",
    "定义": "definition",
    "背景": "background",
}

SYSTEM = (
    "You are Gloss's auto-highlighter. From the paper, select the MOST important "
    "sentences a researcher should notice, each tagged with a category. Copy each "
    "sentence VERBATIM from the text — in the paper's original language, because it "
    "must be locatable in the PDF. Prefer contributions, key methods, headline "
    "results, definitions, and limitations. The 'why' explanation is a note for the "
    "reader and MUST be written in the requested output language."
)

SHAPE = (
    '{"items": [{"text": "verbatim sentence from the paper", '
    '"category": "contribution|method|result|limitation|definition|background", '
    '"why": "short reason"}]}'
)


def _norm_category(raw: str | None) -> str:
    """Map whatever category label the model returned onto a colour key."""
    label = (raw or "").strip().lower()
    if label in CATEGORY_COLORS:
        return label
    exact = CATEGORY_ALIASES.get((raw or "").strip())
    if exact:
        return exact
    for key in CATEGORY_COLORS:
        if key in label:
            return key
    return "background"


async def auto_highlight(
    paper_id: str, *, max_items: int = 24, provider: str | None = None, model: str | None = None
) -> list[dict]:
    parsed = store.load_parsed(paper_id)
    if not parsed:
        raise ValueError("paper not parsed")
    text = truncate_to_tokens(parsed["full_text"], 60000)
    lang = output_language()
    user = (
        f"Select up to {max_items} key sentences (verbatim, in the paper's original "
        f"language so they can be located) with categories.\n"
        f"CRITICAL: every 'why' explanation must be written in {lang} — "
        f"e.g. 中文 (Simplified Chinese) means the note is Chinese even though the "
        f"paper is English. Never answer the 'why' field in English when the "
        f"requested language is Chinese.\n\n=== PAPER ===\n{text}"
    )
    result = await json_complete(SYSTEM, user, SHAPE, provider=provider, model=model)
    items = result.get("items", [])[:max_items]

    pdf = store.pdf_path(paper_id)
    # Drop the previous run's annotations from the PDF before replacing the rows.
    stale = [
        int(h["pdf_xref"])
        for h in store.list_highlights(paper_id, kind="auto")
        if h.get("pdf_xref")
    ]
    store.clear_auto_highlights(paper_id)
    saved = []
    for it in items:
        sent = (it.get("text") or "").strip()
        if len(sent) < 8:
            continue
        loc = ingest.locate_text(pdf, sent)
        if not loc:
            continue
        cat = _norm_category(it.get("category"))
        h = store.add_highlight(paper_id, {
            "page": loc["page"],
            "rects": loc["rects"],
            "color": CATEGORY_COLORS.get(cat, "#ffe082"),
            "category": cat,
            "text": sent,
            "note": it.get("why", ""),
            "kind": "auto",
            # Underlined, not filled: auto highlights cover a lot of text and a
            # fill would bury the page.
            "style": "underline",
        })
        saved.append(h)
    await _replace_pdf_annots(paper_id, stale, saved)
    store.cache_set(paper_id, "autohighlight_done", True)
    return saved


async def _replace_pdf_annots(paper_id: str, stale: list[int], saved: list[dict]) -> None:
    """One pass: remove the old auto annotations, write the new ones."""
    def _work() -> None:
        if stale:
            annot_writer.remove(paper_id, stale)
        if not saved or not annot_writer.enabled():
            return
        written = annot_writer.add(paper_id, saved)
        for h in saved:
            xref = written.get(h["id"])
            if xref is None:
                continue
            store.set_highlight_xref(h["id"], xref)
            h["pdf_xref"] = xref

    await asyncio.to_thread(_work)
