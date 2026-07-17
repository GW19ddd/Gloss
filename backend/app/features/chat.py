"""Grounded chat over a paper (BM25 retrieval + streaming)."""
from __future__ import annotations

from typing import AsyncIterator

from ..config import output_language
from ..library import store
from ..providers import registry
from . import retrieval
from .common import truncate_to_tokens

SYSTEM = (
    "You are Gloss, an AI research colleague discussing a specific paper with the "
    "user. Answer using the paper's content and the retrieved excerpts below. Be "
    "precise and cite section/figure/equation names when relevant. If the answer is "
    "not in the paper, say so and reason carefully. You may discuss limitations and "
    "connections to related work. Render math with $...$. Reply in the user's language."
)


def _build_context(paper_id: str, query: str) -> str:
    parsed = store.load_parsed(paper_id)
    p = store.get_paper(paper_id)
    parts = []
    if p:
        parts.append(f"# Paper\nTitle: {p.get('title','')}")
        if p.get("authors"):
            parts.append("Authors: " + ", ".join(p["authors"][:12]))
        if p.get("abstract"):
            parts.append("Abstract: " + p["abstract"][:2000])
    if parsed:
        secs = parsed.get("sections", [])
        if secs:
            parts.append("Sections: " + " | ".join(s["title"][:40] for s in secs[:25]))
        chunks = retrieval.build_chunks(parsed)
        top = retrieval.retrieve(query, chunks, k=6)
        if top:
            ex = "\n\n".join(
                f"[p.{c['page']+1}] {c['text']}" for c in top
            )
            parts.append("# Retrieved excerpts\n" + truncate_to_tokens(ex, 6000))
    return "\n\n".join(parts)


async def chat_stream(
    paper_id: str,
    messages: list[dict],
    *,
    selection: str | None = None,
    language: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> AsyncIterator[str]:
    query = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            query = m.get("content", "")
            break
    if selection:
        query = f"{selection}\n{query}"

    lang = language or output_language()
    context = _build_context(paper_id, query) if paper_id else ""
    system = SYSTEM + f"\n\nAlways answer in: {lang}." + ("\n\n" + context if context else "")

    convo = list(messages)
    if selection and convo:
        convo = convo[:-1] + [{
            "role": "user",
            "content": f"[Selected text from the paper]:\n{selection}\n\n{convo[-1].get('content','')}",
        }]

    async for chunk in registry.stream(system, convo, provider=provider, model=model):
        yield chunk
