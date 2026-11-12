"""Zotero endpoints: link a paper to a Zotero item and export notes that jump back.

The note HTML is rendered by the frontend (marked + KaTeX, so formulas survive).
This router creates the annotations, injects ``zotero://open-pdf`` links in place
of the ``[E1]`` markers, and writes the note into Zotero as a **standalone
entry** — not as a child note of the paper, so it stays out of the way of the
user's own child notes.

Zotero 10 answers write requests once Gloss holds a local API key, which is what
:func:`authorize` below obtains. Older Zoteros are read-only, and there the
endpoint degrades to handing the HTML back for the user to paste.
"""
from __future__ import annotations

import re
from xml.sax.saxutils import escape

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import config, zotero
from ..library import store

router = APIRouter(prefix="/api", tags=["zotero"])

_EVIDENCE_MARK = re.compile(r"\[([A-Za-z]+\d+)\]")


class LinkBody(BaseModel):
    item_key: str | None = None
    attachment_key: str | None = None


class EvidenceIn(BaseModel):
    id: str = ""
    quote: str = ""
    why: str = ""
    page: int | None = None
    rects: list[list[float]] = Field(default_factory=list)


class ExportBody(BaseModel):
    html: str
    evidence: list[EvidenceIn] = Field(default_factory=list)
    item_key: str | None = None
    attachment_key: str | None = None
    #: Set to overwrite the note a previous export created instead of adding
    #: another one. Never guessed: an unknown key would silently create.
    note_key: str | None = None


def _paper_or_404(paper_id: str) -> dict:
    paper = store.get_paper(paper_id)
    if not paper:
        raise HTTPException(404, "paper not found")
    return paper


def _source_pdf(paper_id: str) -> str | None:
    path = store.linked_source_pdf(paper_id)
    return str(path) if path else None


@router.get("/zotero/status")
async def zotero_status():
    """Is Zotero running and reachable over its local API?"""
    return await zotero.status()


@router.post("/zotero/authorize")
async def authorize():
    """Ask Zotero for a local API key; blocks until the user answers the modal.

    Zotero opens "Allow / Always Allow / Deny". Only *Always Allow* gives a key
    that lasts — *Allow* is single-use and the next write consumes it — so the
    response reports ``remember`` and the UI can warn when it got the wrong one.
    """
    if not await zotero.ping():
        raise HTTPException(503, "Zotero is not running")
    try:
        result = await zotero.authorize()
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    return {**result, "status": await zotero.status()}


@router.get("/zotero/search")
async def search_library(q: str = "", limit: int = 10):
    """Free-text lookup, for the times automatic matching misses the item."""
    if not await zotero.ping():
        raise HTTPException(503, "Zotero is not running")
    if not q.strip():
        return {"candidates": []}
    candidates = await zotero.search_all_modes(q.strip(), min(max(limit, 1), 25))
    for item in candidates:
        item["attachments"] = await zotero.pdf_attachments(item["key"])
    return {"candidates": candidates}


@router.get("/papers/{paper_id}/zotero/link")
async def get_link(paper_id: str):
    """Stored Zotero keys for this paper plus the current Zotero status."""
    _paper_or_404(paper_id)
    return {"link": store.zotero_link(paper_id), "status": await zotero.status()}


@router.post("/papers/{paper_id}/zotero/match")
async def match(paper_id: str):
    """Candidate Zotero items for this paper (DOI → arXiv → title → filename)."""
    paper = _paper_or_404(paper_id)
    if not await zotero.ping():
        raise HTTPException(503, "Zotero is not running")
    candidates = await zotero.match_paper(paper, _source_pdf(paper_id))
    return {"candidates": candidates, "link": store.zotero_link(paper_id)}


@router.post("/papers/{paper_id}/zotero/link")
async def link(paper_id: str, body: LinkBody):
    """Bind the paper to a Zotero item, picking its PDF attachment."""
    _paper_or_404(paper_id)
    if not body.item_key:
        raise HTTPException(400, "item_key is required")
    attachment_key = body.attachment_key
    if not attachment_key:
        attachments = await zotero.pdf_attachments(body.item_key)
        picked = zotero.pick_attachment(attachments, _source_pdf(paper_id))
        attachment_key = picked["key"] if picked else None
    store.set_zotero_link(
        paper_id, item_key=body.item_key, attachment_key=attachment_key
    )
    return {"link": store.zotero_link(paper_id)}


@router.get("/papers/{paper_id}/zotero/annotations")
async def list_annotations(paper_id: str):
    """Annotations Zotero already has on the linked PDF (for two-way sync)."""
    _paper_or_404(paper_id)
    link = store.zotero_link(paper_id)
    if not link["attachment_key"]:
        return {"annotations": [], "reason": "no Zotero PDF linked"}
    return {"annotations": await zotero.annotations(link["attachment_key"])}


def _evidence_block(results: list[dict], attachment_key: str) -> str:
    heading = "证据" if "中文" in config.output_language() else "Evidence"
    rows = []
    for r in results:
        if r.get("page") is None:
            continue
        url = zotero.open_pdf_url(attachment_key, r["page"], r.get("key"))
        page = (r.get("page") or 0) + 1
        why = (r.get("why") or "").replace("<", "&lt;")
        rows.append(
            f'<li><a href="{url}">[{r.get("evidence_id")}]</a> (p.{page})'
            f"{f' — {why}' if why else ''}</li>"
        )
    if not rows:
        return ""
    return f'<hr /><h2>{heading}</h2><ul>{"".join(rows)}</ul>'


def _note_header(paper: dict, item_key: str) -> str:
    """Title block topping the exported note.

    Zotero lists a standalone note under its first line, so the paper title has
    to come first — without it every export shows up as an untitled snippet.
    The link selects the paper the note belongs to.
    """
    title = (paper.get("title") or "").strip() or "Untitled"
    url = zotero.select_url(item_key)
    return f'<h1><a href="{url}">{escape(title)}</a></h1>'


async def _ensure_writable() -> bool:
    """Whether Zotero will take writes now, asking for a key the first time.

    Blocks while Zotero shows its authorization modal. A refusal — or an older
    Zotero — leaves Gloss on the read-only path instead of failing the export.
    """
    if not await zotero.server_id():
        return False
    if zotero.authorized():
        return True
    try:
        await zotero.authorize()
        return True
    except RuntimeError:
        return False


@router.post("/papers/{paper_id}/zotero/export")
async def export(paper_id: str, body: ExportBody):
    """Create the annotations and put the note in Zotero as an entry of its own.

    On a Zotero that takes writes this finishes the job: highlights are added to
    the PDF, a new note appears in the library, and every ``[E1]`` marker becomes
    a ``zotero://open-pdf`` link that jumps to the passage. On a read-only
    Zotero nothing is written and the HTML comes back for the user to paste.
    """
    paper = _paper_or_404(paper_id)
    if not await zotero.ping():
        raise HTTPException(503, "Zotero is not running")

    link = store.zotero_link(paper_id)
    item_key = body.item_key or link["item_key"]
    if not item_key:
        raise HTTPException(400, "this paper is not linked to a Zotero item yet")

    attachment_key = body.attachment_key or link["attachment_key"]
    if not attachment_key:
        attachments = await zotero.pdf_attachments(item_key)
        picked = zotero.pick_attachment(attachments, _source_pdf(paper_id))
        attachment_key = picked["key"] if picked else None
    if not attachment_key:
        raise HTTPException(400, "that Zotero item has no PDF attachment")

    can_write = await _ensure_writable()
    evidence = [e.model_dump() for e in body.evidence]
    if can_write:
        results = await zotero.create_annotations(attachment_key, evidence)
    else:
        results = await zotero.resolve_annotations(attachment_key, evidence)

    by_id = {str(r.get("evidence_id")): r for r in results}

    def _replace(match: re.Match) -> str:
        token = match.group(0)
        found = by_id.get(match.group(1))
        if not found or found.get("page") is None:
            return token
        # unmatched evidence still gets a page-accurate link
        url = zotero.open_pdf_url(attachment_key, found["page"], found.get("key"))
        return f'<a href="{url}">{token}</a>'

    html = _EVIDENCE_MARK.sub(_replace, body.html or "")
    html += _evidence_block(results, attachment_key)

    note_key = body.note_key or link["note_key"]
    if can_write:
        # Notes from earlier versions sit at the library root; re-parenting is
        # not possible via a plain update, so start a child note instead.
        if note_key and await zotero.note_parent(note_key) != item_key:
            note_key = None
        try:
            note_key = (
                await zotero.put_note(
                    _note_header(paper, item_key) + html, note_key, parent=item_key
                )
            ).get("key")
        except (zotero.NotAuthorized, RuntimeError):
            # Never fail the export over the note: the annotations are in and
            # the HTML still comes back for a manual paste.
            note_key = None

    store.set_zotero_link(
        paper_id, item_key=item_key, attachment_key=attachment_key, note_key=note_key
    )
    return {
        "html": html,
        "item_key": item_key,
        "attachment_key": attachment_key,
        "note_updated": bool(body.note_key) and note_key == body.note_key,
        "select_url": zotero.select_url(item_key),
        "note_key": note_key,
        "note_url": zotero.select_url(note_key) if note_key else None,
        "written": bool(note_key),
        "annotations": results,
        # A link only jumps to the passage when it names an annotation; without
        # one it opens the right page and stops there.
        "matched": len([r for r in results if r.get("key")]),
        "total": len(results),
        "writable": (await zotero.server_id()) is not None,
        "authorized": zotero.authorized(),
    }
