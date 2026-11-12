"""User highlights + annotations (markup tools) and chat-history CRUD.

Highlights are stored in Gloss's database *and* written into the PDF file itself
as standard, editable PDF highlight annotations (see ``pdf/annot_writer.py``),
so they survive being opened in Acrobat / Preview / Zotero.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, NamedTuple

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, field_validator

from ..library import store
from ..pdf import annot_reader, annot_writer, bilingual

router = APIRouter(prefix="/api", tags=["annotations"])


class HighlightBody(BaseModel):
    page: int
    rects: list[list[float]]
    text: str = ""
    color: str = "#ffd54f"
    note: str = ""
    category: str = ""


class HighlightPatch(BaseModel):
    color: str | None = None
    note: str | None = None
    category: str | None = None


class DrawingBody(BaseModel):
    page: int = Field(ge=0)
    points: list[list[float]] = Field(min_length=2, max_length=5000)
    color: str = Field(default="#ef6b6b", max_length=32)
    width: float = Field(default=3, ge=1, le=36)
    tool: Literal["pencil", "pen", "highlighter"] = "pen"
    note: str = Field(default="", max_length=2000)

    @field_validator("points")
    @classmethod
    def validate_points(cls, points: list[list[float]]) -> list[list[float]]:
        for point in points:
            if len(point) != 2:
                raise ValueError("each drawing point must contain x and y")
            if not all(-10000 <= float(value) <= 100000 for value in point):
                raise ValueError("drawing point is outside the supported range")
        return points


class PersonalNoteBody(BaseModel):
    content: str = Field(default="", max_length=1_000_000)


@router.get("/papers/{paper_id}/highlights")
async def list_highlights(paper_id: str, kind: str | None = None):
    if not store.get_paper(paper_id):
        raise HTTPException(404, "paper not found")
    return {"highlights": store.list_highlights(paper_id, kind=kind)}


@router.post("/papers/{paper_id}/highlights")
async def add_highlight(paper_id: str, body: HighlightBody):
    if not store.get_paper(paper_id):
        raise HTTPException(404, "paper not found")
    h = store.add_highlight(paper_id, {**body.model_dump(), "kind": "user"})
    await _write_to_pdf(paper_id, [h])
    return h


@router.patch("/highlights/{hid}")
async def patch_highlight(hid: str, body: HighlightPatch):
    h = store.update_highlight(hid, body.model_dump(exclude_none=True))
    if not h:
        raise HTTPException(404, "highlight not found")
    await _refresh_in_pdf(h)
    return h


@router.delete("/highlights/{hid}")
async def delete_highlight(hid: str):
    h = store.get_highlight(hid)
    if h and h.get("pdf_xref"):
        await run_in_threadpool(
            annot_writer.remove, h.get("paper_id"), [int(h["pdf_xref"])]
        )
    store.delete_highlight(hid)
    return {"ok": True}


@router.post("/papers/{paper_id}/highlights/sync-pdf")
async def sync_highlights_to_pdf(paper_id: str):
    """Rewrite the PDF's Gloss annotations from the database.

    Use after the sync setting was turned back on, or when annotations were
    edited outside Gloss. Never touches annotations created by other readers.
    """
    if not store.get_paper(paper_id):
        raise HTTPException(404, "paper not found")
    result = await run_in_threadpool(annot_writer.sync_paper, paper_id)
    return {**result, "highlights": store.list_highlights(paper_id)}


async def _write_to_pdf(paper_id: str, highlights: list[dict]) -> None:
    """Create native PDF annotations and remember their xrefs."""
    if not highlights or not annot_writer.enabled():
        return
    written = await run_in_threadpool(annot_writer.add, paper_id, highlights)
    for highlight in highlights:
        xref = written.get(highlight["id"])
        if xref is not None:
            store.set_highlight_xref(highlight["id"], xref)
        highlight["pdf_xref"] = xref


async def _refresh_in_pdf(highlight: dict) -> None:
    """Push a colour/note edit into the PDF, recreating the annotation if the
    stored xref no longer resolves (e.g. the file was edited elsewhere)."""
    if not annot_writer.enabled():
        return
    paper_id = highlight.get("paper_id")
    if not paper_id:
        return
    if highlight.get("pdf_xref"):
        found = await run_in_threadpool(
            annot_writer.update, paper_id, [highlight]
        )
        if found:
            highlight["pdf_xref"] = found[highlight["id"]]
            return
    written = await run_in_threadpool(
        annot_writer.ensure, paper_id, [highlight]
    )
    xref = written.get(highlight["id"])
    if xref is not None:
        store.set_highlight_xref(highlight["id"], xref)
    highlight["pdf_xref"] = xref


# Every place evidence can be written. "copy" is Gloss's own copy of the PDF: it
# never reaches the file the reader linked from Zotero.
TARGETS = Literal["auto", "original", "dual", "mono", "both", "copy"]
SIDES = Literal["original", "translated", "both"]


class EvidenceBody(BaseModel):
    evidence: list[dict] = Field(default_factory=list)
    # Where the highlights go: Gloss's own copy, the source PDF, a PaperFlow
    # translation, or both.
    target: TARGETS = "auto"
    # On a translation: its original pages, its translated pages, or both — the
    # last one being how a bilingual file ends up marked on both sides of the
    # spread, since the translation side is found from the original one.
    side: SIDES = "original"


class Target(NamedTuple):
    """A PDF to write evidence into, and what to do once it is there."""

    path: Path
    evidence: list[dict]
    mirror: bool = False


def _prepare_evidence(
    paper_id: str, target: str, side: str, evidence: list[dict]
) -> list[Target]:
    """Pick the PDF(s) to write to, with the evidence mapped onto each.

    The source file keeps the evidence as-is. A translation needs its pages and
    rectangles mapped too, because pdf2zh re-typesets the translated pages, and
    the mapping always starts from the original: that is the side the quote was
    located on. "both" as a target writes the source *and* the translation;
    "both" as a side marks the original page of a bilingual file and mirrors the
    mark onto the translated page facing it.
    """
    # "auto" is offered as "write the bilingual file, both columns", so a
    # defaulted side must not quietly narrow that to the original column —
    # the reader who wants one column picks dual:original explicitly.
    if target == "auto" and side == "original":
        side = "both"

    # "copy" is the safe default: one file, the copy inside Gloss's own library.
    # It never reaches the PDF the reader linked from Zotero, and it never fans
    # out into translation siblings, so what gets written is predictable.
    if target == "copy":
        return [Target(store.pdf_path(paper_id), [dict(e) for e in evidence])]

    source = annot_writer.target_path(paper_id)
    dual = bilingual.dual_path_for(source)
    mono = bilingual.mono_path_for(source)

    def on_dual() -> Target:
        # "both" is the original side plus a mirror: one English mark, one on the
        # translation facing it, never two marks for one piece of evidence.
        if side == "translated":
            return Target(
                dual,
                bilingual.map_evidence_to_translated(
                    dual, evidence, source_path=source
                ),
            )
        return Target(
            dual,
            bilingual.map_evidence(dual, evidence, source_path=source),
            mirror=side == "both",
        )

    def on_mono() -> Target:
        return Target(
            mono,
            bilingual.map_evidence_to_translated(mono, evidence, source_path=source),
        )

    def on_own_dual(kind_: str = "dual") -> Target:
        """The paper is read in the bilingual file itself.

        The reader imported it, so Gloss's copy is the bilingual file and every
        page number already indexes it. A dual holds page 2p as an original and
        2p+1 as its translation — which ``map_evidence_to_translated`` reaches by
        being told the file is a dual and handed source page numbers. A
        side_by_side keeps one page per source page and carries the source's own
        coordinates in its original column, so nothing has to be remapped at all.
        """
        if kind_ == "side_by_side":
            if side == "translated":
                return Target(
                    source,
                    bilingual.map_evidence_to_translated(
                        source, evidence, kind_="side_by_side"
                    ),
                )
            return Target(source, [dict(e) for e in evidence], mirror=side == "both")
        if side == "translated":
            halved = []
            for item in evidence:
                try:
                    page = int(item.get("page"))
                except (TypeError, ValueError):
                    halved.append(dict(item))
                    continue
                halved.append(dict(item, page=page // 2))
            return Target(
                source,
                bilingual.map_evidence_to_translated(source, halved, kind_="dual"),
            )
        return Target(source, [dict(e) for e in evidence], mirror=side == "both")

    # No linked original: the copy Gloss reads is the one being written, and it
    # may itself be bilingual — a bilingual file imported straight into Gloss.
    own_kind = (
        annot_writer.paper_pdf_kind(paper_id)
        if annot_writer.writes_own_copy(paper_id)
        else "original"
    )
    if own_kind in ("dual", "side_by_side"):
        return [on_own_dual(own_kind)]

    # A linked original can be bilingual without being the one on screen:
    # PaperFlow's side_by_side, found through Zotero. It holds a source page per
    # page, so the evidence page numbers index it as they stand — and the mark
    # still has to reach the translation beside it.
    if target in ("auto", "dual"):
        if annot_writer._target_kind(paper_id, source) == "side_by_side":
            return [on_own_dual("side_by_side")]

    if target == "mono":
        if mono is None:
            return [Target(source, evidence)]
        return [on_mono()]
    if target == "dual" or (target == "auto" and dual is not None):
        if dual is None:
            return [Target(source, evidence)]
        return [on_dual()]
    if target == "both":
        targets = [Target(source, [dict(e) for e in evidence])]
        if dual is not None:
            targets.append(on_dual())
        elif mono is not None:
            targets.append(on_mono())
        return targets
    return [Target(source, evidence)]


def _count_targets(paper_id: str, targets: list[Target]) -> int:
    """Evidence annotations across every file a target resolves to."""
    return sum(
        annot_writer.count_evidence(paper_id, path=t.path) for t in targets
    )


def _remove_targets(paper_id: str, targets: list[Target]) -> int:
    return sum(
        annot_writer.remove_evidence(paper_id, path=t.path) for t in targets
    )


@router.get("/papers/{paper_id}/evidence/pdf")
async def evidence_pdf_status(
    paper_id: str, target: TARGETS = "auto", side: SIDES = "original"
):
    if not store.get_paper(paper_id):
        raise HTTPException(404, "paper not found")
    # Counted against the selected file, so the number matches what the
    # "write to PDF" choice would actually touch.
    total = await run_in_threadpool(
        _count_targets, paper_id, _prepare_evidence(paper_id, target, side, [])
    )
    source = annot_writer.target_path(paper_id)
    dual = bilingual.dual_path_for(source)
    mono = bilingual.mono_path_for(source)
    # The bilingual file may be the one Gloss reads, imported under its own name.
    own_dual = annot_writer.writes_own_copy(paper_id) and (
        annot_writer.paper_pdf_kind(paper_id) in ("dual", "side_by_side")
    )
    return {
        "embedded": total,
        "dual": {
            "available": own_dual or dual is not None,
            "path": str(store.pdf_path(paper_id)) if own_dual else (
                str(dual) if dual else None
            ),
            "sidecar": bilingual.sidecar_path_for(source) is not None,
        },
        "mono": {
            "available": mono is not None,
            "path": str(mono) if mono else None,
        },
    }


@router.post("/papers/{paper_id}/evidence/pdf")
async def write_evidence_to_pdf(paper_id: str, body: EvidenceBody):
    """Write the note's evidence into the PDF as native annotations.

    Every PDF reader shows them, and Zotero imports them as annotations the next
    time the file is opened — which is what lets an exported note link land on
    the right highlight instead of just the right page.
    """
    if not store.get_paper(paper_id):
        raise HTTPException(404, "paper not found")
    targets = _prepare_evidence(paper_id, body.target, body.side, body.evidence)
    results: list[dict] = []
    for t in targets:
        results.extend(
            await run_in_threadpool(
                annot_writer.add_evidence,
                paper_id,
                t.evidence,
                path=t.path,
                mirror=t.mirror,
            )
        )
    return {
        "written": len([r for r in results if r.get("xref") is not None]),
        "skipped": len([r for r in results if r.get("skipped")]),
        "results": results,
        "targets": [str(t.path) for t in targets],
        "embedded": await run_in_threadpool(_count_targets, paper_id, targets),
    }


@router.delete("/papers/{paper_id}/evidence/pdf")
async def clear_evidence_from_pdf(
    paper_id: str, target: TARGETS = "auto", side: SIDES = "original"
):
    """Remove the evidence annotations Gloss wrote into the PDF."""
    if not store.get_paper(paper_id):
        raise HTTPException(404, "paper not found")
    removed = await run_in_threadpool(
        _remove_targets, paper_id, _prepare_evidence(paper_id, target, side, [])
    )
    return {"removed": removed}


@router.get("/papers/{paper_id}/pdf-annotations")
async def list_pdf_annotations(paper_id: str):
    """Every markup annotation inside the PDF itself.

    The database only holds the highlights Gloss made. Everything else in the
    file — note evidence written for a reader, and marks Zotero or another
    reader left there — lives in the PDF alone, and this is how Gloss sees it.
    """
    if not store.get_paper(paper_id):
        raise HTTPException(404, "paper not found")
    return {
        "annotations": await run_in_threadpool(
            annot_reader.list_annotations, paper_id
        )
    }


@router.delete("/papers/{paper_id}/pdf-annotations/{xref}")
async def delete_pdf_annotation(paper_id: str, xref: int, source: str = "copy"):
    """Delete one annotation from the file it was read from.

    ``source`` says which: the copy Gloss renders, or the linked original. The
    same xref numbers different objects in the two files, so it cannot be
    guessed from the number alone.
    """
    if not store.get_paper(paper_id):
        raise HTTPException(404, "paper not found")
    removed = await run_in_threadpool(
        annot_reader.remove_annotations, paper_id, [xref],
        "original" if source == "original" else "copy",
    )
    return {"removed": removed}


@router.get("/papers/{paper_id}/drawings")
async def list_drawings(paper_id: str):
    if not store.get_paper(paper_id):
        raise HTTPException(404, "paper not found")
    return {"drawings": store.list_drawings(paper_id)}


@router.post("/papers/{paper_id}/drawings")
async def add_drawing(paper_id: str, body: DrawingBody):
    if not store.get_paper(paper_id):
        raise HTTPException(404, "paper not found")
    return store.add_drawing(paper_id, body.model_dump())


@router.delete("/drawings/{drawing_id}")
async def delete_drawing(drawing_id: str):
    store.delete_drawing(drawing_id)
    return {"ok": True}


@router.get("/papers/{paper_id}/personal-note")
async def get_personal_note(paper_id: str):
    if not store.get_paper(paper_id):
        raise HTTPException(404, "paper not found")
    return store.get_personal_note(paper_id)


@router.put("/papers/{paper_id}/personal-note")
async def save_personal_note(paper_id: str, body: PersonalNoteBody):
    if not store.get_paper(paper_id):
        raise HTTPException(404, "paper not found")
    return store.save_personal_note(paper_id, body.content)


# ---- chat history ----
class ChatCreate(BaseModel):
    title: str = "Chat"


class ChatPatch(BaseModel):
    title: str = Field(min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def validate_title(cls, title: str) -> str:
        normalized = " ".join(title.split())
        if not normalized:
            raise ValueError("title cannot be blank")
        return normalized


@router.get("/papers/{paper_id}/chats")
async def list_chats(paper_id: str):
    return {"chats": store.list_chats(paper_id)}


@router.post("/papers/{paper_id}/chats")
async def create_chat(paper_id: str, body: ChatCreate):
    if not store.get_paper(paper_id):
        raise HTTPException(404, "paper not found")
    return store.create_chat(paper_id, body.title)


@router.get("/chats/{chat_id}/messages")
async def chat_messages(chat_id: str):
    return {"messages": store.list_messages(chat_id)}


@router.patch("/chats/{chat_id}")
async def update_chat(chat_id: str, body: ChatPatch):
    chat = store.update_chat_title(chat_id, body.title)
    if not chat:
        raise HTTPException(404, "chat not found")
    return {
        "id": chat["id"],
        "paper_id": chat["paper_id"],
        "title": chat["title"],
        "created_at": chat["created_at"],
    }


@router.delete("/chats/{chat_id}")
async def delete_chat(chat_id: str):
    store.delete_chat(chat_id)
    return {"ok": True}
