"""Library / paper endpoints: import, list, read, delete."""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..library import importers, service, store
from ..pdf import ingest, structure

router = APIRouter(prefix="/api/papers", tags=["papers"])


class ImportBody(BaseModel):
    query: str | None = None
    arxiv: str | None = None
    doi: str | None = None
    url: str | None = None


class PaperPatch(BaseModel):
    title: str | None = None
    tags: list[str] | None = None
    year: str | None = None


@router.get("")
async def list_papers():
    return {"papers": store.list_papers()}


@router.post("/upload")
async def upload_paper(file: UploadFile = File(...)):
    data = await file.read()
    try:
        paper = await run_in_threadpool(
            service.create_from_pdf_bytes, data, {"source": "upload", "title": ""}
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return paper


@router.post("/import")
async def import_paper(body: ImportBody):
    try:
        meta, pdf = await importers.import_source(body.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # network / http errors
        raise HTTPException(502, f"Import failed: {e}")
    try:
        paper = await run_in_threadpool(service.create_from_pdf_bytes, pdf, meta)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return paper


@router.get("/{paper_id}")
async def get_paper(paper_id: str):
    p = store.get_paper(paper_id)
    if not p:
        raise HTTPException(404, "paper not found")
    return p


@router.patch("/{paper_id}")
async def patch_paper(paper_id: str, body: PaperPatch):
    if not store.get_paper(paper_id):
        raise HTTPException(404, "paper not found")
    store.update_paper(paper_id, body.model_dump(exclude_none=True))
    return store.get_paper(paper_id)


@router.delete("/{paper_id}")
async def delete_paper(paper_id: str):
    if not store.get_paper(paper_id):
        raise HTTPException(404, "paper not found")
    store.delete_paper(paper_id)
    return {"ok": True}


@router.get("/{paper_id}/pdf")
async def get_pdf(paper_id: str):
    p = store.pdf_path(paper_id)
    if not p.exists():
        raise HTTPException(404, "pdf not found")
    return FileResponse(str(p), media_type="application/pdf", filename=f"{paper_id}.pdf")


@router.get("/{paper_id}/pages")
async def get_pages(paper_id: str):
    parsed = store.load_parsed(paper_id)
    if not parsed:
        raise HTTPException(404, "parsed data not found")
    # recompute sections from stored blocks so heuristic improvements apply to
    # already-ingested papers without re-parsing the PDF
    sections = structure.detect_sections(parsed)
    return {
        "n_pages": parsed["n_pages"],
        "pages": parsed["pages"],
        "sections": sections,
        "toc": parsed.get("toc", []),
    }


class LocateBody(BaseModel):
    text: str


@router.post("/{paper_id}/locate")
async def locate(paper_id: str, body: LocateBody):
    """Find where a snippet appears in the PDF → {page, rects} (for click-to-highlight)."""
    if not store.get_paper(paper_id):
        raise HTTPException(404, "paper not found")
    loc = await run_in_threadpool(ingest.locate_text, store.pdf_path(paper_id), body.text)
    return loc or {"page": None, "rects": []}


@router.get("/{paper_id}/fulltext")
async def get_fulltext(paper_id: str):
    parsed = store.load_parsed(paper_id)
    if not parsed:
        raise HTTPException(404, "parsed data not found")
    return {"full_text": parsed["full_text"]}
