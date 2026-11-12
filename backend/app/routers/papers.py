"""Library / paper endpoints: import, list, read, delete."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..library import importers, service, store
from ..library.import_jobs import (
    ImportCleanupError,
    ImportJobManager,
    ImportQueueFullError,
)
from ..features import outline as outline_feat
from ..pdf import annot_writer, ingest, original_finder, reflow, structure

router = APIRouter(prefix="/api/papers", tags=["papers"])


def _bounded_import_timeout(name: str, *, default: float = 120) -> float:
    try:
        configured = float(os.environ.get(name, str(default)))
    except ValueError:
        configured = 120
    return max(1, min(configured, 300))


IMPORT_DOWNLOAD_TIMEOUT = _bounded_import_timeout("GLOSS_IMPORT_TIMEOUT", default=300)
IMPORT_PARSE_TIMEOUT = _bounded_import_timeout("GLOSS_IMPORT_PARSE_TIMEOUT")
IMPORT_SAVE_TIMEOUT = _bounded_import_timeout("GLOSS_IMPORT_SAVE_TIMEOUT")


class ImportBody(BaseModel):
    query: str | None = None
    arxiv: str | None = None
    doi: str | None = None
    url: str | None = None


class PaperPatch(BaseModel):
    title: str | None = None
    tags: list[str] | None = None
    year: str | None = None


class PdfTargetBody(BaseModel):
    """Absolute path of the paper's original PDF (its Zotero attachment)."""
    path: str = Field(min_length=1, max_length=4096)


@router.get("")
async def list_papers():
    return {"papers": store.list_papers()}


@router.post("/upload")
async def upload_paper(file: UploadFile = File(...)):
    data = await file.read()
    try:
        paper = await run_in_threadpool(
            service.create_from_pdf_bytes,
            data,
            {
                "source": "upload",
                "title": "",
                # the name the file arrived under, before Gloss stores it as
                # original.pdf: "…-dual.pdf" is a PaperFlow bilingual file
                "file_name": file.filename or "",
            },
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return paper


@router.post("/import")
async def import_paper(body: ImportBody):
    try:
        meta, pdf = await asyncio.wait_for(
            importers.import_source(body.model_dump(exclude_none=True)),
            timeout=IMPORT_DOWNLOAD_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            504,
            f"Import timed out after {IMPORT_DOWNLOAD_TIMEOUT:g}s while downloading the paper",
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # network / http errors
        raise HTTPException(502, f"Import failed: {e}")
    try:
        parsed = await run_in_threadpool(
            service.parse_pdf_bytes_with_timeout,
            pdf,
            IMPORT_PARSE_TIMEOUT,
        )
    except TimeoutError:
        raise HTTPException(
            504,
            f"Import timed out after {IMPORT_PARSE_TIMEOUT:g}s while parsing the PDF",
        )
    try:
        paper = await run_in_threadpool(
            service.create_from_pdf_bytes, pdf, meta, parsed
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return paper


def _import_job_manager(request: Request) -> ImportJobManager:
    manager = getattr(request.app.state, "import_jobs", None)
    if manager is None:
        raise HTTPException(503, "import queue is not ready")
    return manager


@router.post("/import-jobs", status_code=status.HTTP_202_ACCEPTED)
async def enqueue_import(body: ImportBody, request: Request):
    manager = _import_job_manager(request)
    try:
        return await manager.submit(body.model_dump(exclude_none=True))
    except ImportQueueFullError as error:
        raise HTTPException(429, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from error


@router.get("/import-jobs")
async def list_import_jobs(request: Request):
    return {"jobs": await _import_job_manager(request).list()}


@router.get("/import-jobs/{job_id}")
async def get_import_job(job_id: str, request: Request):
    job = await _import_job_manager(request).get(job_id)
    if job is None:
        raise HTTPException(404, "import job not found")
    return job


@router.delete("/import-jobs/{job_id}")
async def cancel_or_clear_import_job(job_id: str, request: Request):
    try:
        removed = await _import_job_manager(request).cancel_or_clear(job_id)
    except ImportCleanupError as error:
        raise HTTPException(500, str(error)) from error
    if not removed:
        raise HTTPException(404, "import job not found")
    return {"ok": True}


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


def _resolve_original(paper_id: str, raw: str) -> Path:
    """Validate a user-supplied original-PDF path before we start writing to it."""
    try:
        path = Path(raw).expanduser()
    except (OSError, ValueError):
        raise HTTPException(400, "invalid PDF path")
    if not path.is_absolute():
        raise HTTPException(400, "original PDF path must be absolute")
    if not path.exists():
        raise HTTPException(404, f"no such file: {path}")
    if not path.is_file() or path.suffix.lower() != ".pdf":
        raise HTTPException(400, "original PDF path must point to a .pdf file")
    if not os.access(path, os.W_OK):
        raise HTTPException(400, f"that file is read-only: {path}")
    # os.access only checks the read-only flag on Windows — a PDF held open by
    # Zotero or a reader passes it yet refuses every write. Probe a real write
    # handle now (open "r+b" does not truncate) so the error says why, instead
    # of failing later deep inside the annotation sync.
    try:
        with open(path, "r+b"):
            pass
    except OSError as e:
        raise HTTPException(
            400,
            "that file is locked by another program (Zotero / a PDF reader?) — "
            f"close it and retry / 文件正被其他程序占用，请关闭后重试: {e}",
        )
    try:
        if path.resolve() == store.pdf_path(paper_id).resolve():
            raise HTTPException(
                400, "that is Gloss's own working copy — link the original file instead"
            )
    except OSError:
        pass
    try:
        with open(path, "rb") as fh:
            head = fh.read(5)
    except OSError as e:
        raise HTTPException(400, f"cannot read that file: {e}")
    if head != b"%PDF-":
        raise HTTPException(400, "that file is not a PDF")
    return path


@router.get("/{paper_id}/pdf-target")
async def get_pdf_target(paper_id: str):
    """Where annotations are currently written (Gloss copy vs. the original)."""
    if not store.get_paper(paper_id):
        raise HTTPException(404, "paper not found")
    return annot_writer.target_info(paper_id)


@router.post("/{paper_id}/pdf-target")
async def link_pdf_target(paper_id: str, body: PdfTargetBody):
    """Link the paper to its original PDF and push existing annotations into it.

    From here on every highlight is written into that file — the one Zotero,
    Preview or Acrobat open — instead of Gloss's internal copy.
    """
    if not store.get_paper(paper_id):
        raise HTTPException(404, "paper not found")
    path = _resolve_original(paper_id, body.path)
    store.set_paper_source_pdf(paper_id, str(path))
    # xrefs are file-local: they refer to the copy we were writing before.
    store.clear_highlight_xrefs(paper_id)
    try:
        result = await run_in_threadpool(annot_writer.sync_paper, paper_id)
    except Exception as e:
        # Back out: half-linked (target switched, annotations not written) is
        # worse than staying on the internal copy with a clear error.
        store.clear_highlight_xrefs(paper_id)
        store.set_paper_source_pdf(paper_id, None)
        raise HTTPException(
            500,
            "could not write annotations into that file "
            f"/ 写入该文件失败: {e}",
        )
    return {"target": annot_writer.target_info(paper_id), "sync": result}


@router.delete("/{paper_id}/pdf-target")
async def unlink_pdf_target(paper_id: str):
    """Stop writing into the original; annotations go back to Gloss's own copy."""
    if not store.get_paper(paper_id):
        raise HTTPException(404, "paper not found")
    store.clear_highlight_xrefs(paper_id)
    store.set_paper_source_pdf(paper_id, None)
    return annot_writer.target_info(paper_id)


@router.post("/{paper_id}/pdf-target/detect")
async def detect_pdf_target(paper_id: str):
    """Look for the paper's original PDF in Zotero's storage / configured dirs."""
    paper = store.get_paper(paper_id)
    if not paper:
        raise HTTPException(404, "paper not found")
    candidates = await run_in_threadpool(original_finder.find_candidates, paper)
    return {
        "candidates": candidates,
        "searched": [str(d) for d in original_finder.search_dirs()],
    }


@router.get("/{paper_id}/pages")
async def get_pages(paper_id: str, language: str | None = None):
    parsed = store.load_parsed(paper_id)
    if not parsed:
        raise HTTPException(404, "parsed data not found")
    # recompute sections from stored blocks so heuristic improvements apply to
    # already-ingested papers without re-parsing the PDF
    sections = structure.detect_sections(parsed)
    # an AI-cleaned outline (if the user ran one) overrides the raw extraction;
    # otherwise flag a messy outline so the client can offer/trigger a fix.
    # It follows the answer language: Chinese and English are cached apart.
    current = outline_feat.get_outline(paper_id, language, sections=sections)
    sections = current["sections"]
    outline_noisy = False if current["fixed"] else outline_feat.is_noisy(sections)
    labels: list[str | None] = []
    try:
        labels = await run_in_threadpool(ingest.page_labels, store.pdf_path(paper_id))
    except Exception:
        # A page label is a nicety; a PDF we can't read for labels is still
        # readable, so the UI falls back to the position in the file.
        labels = []
    return {
        "n_pages": parsed["n_pages"],
        "pages": parsed["pages"],
        "sections": sections,
        "outline_fixed": current["fixed"],
        "outline_noisy": outline_noisy,
        "outline_written": outline_feat.pdf_written(paper_id),
        "outline_language": current["language"],
        "toc": parsed.get("toc", []),
        "page_labels": labels,
    }


class OutlinePdfBody(BaseModel):
    language: str | None = None


@router.post("/{paper_id}/outline/to-pdf")
async def write_outline_to_pdf(paper_id: str, body: OutlinePdfBody):
    """Make the outline currently shown the PDF's own bookmarks.

    The bookmarks the file had are kept aside so ``restore-pdf`` can undo this.
    """
    if not store.get_paper(paper_id):
        raise HTTPException(404, "paper not found")
    try:
        return await run_in_threadpool(
            outline_feat.write_to_pdf, paper_id, language=body.language
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{paper_id}/outline/restore-pdf")
async def restore_pdf_outline(paper_id: str):
    """Undo a previous write: put the PDF's original bookmarks back."""
    if not store.get_paper(paper_id):
        raise HTTPException(404, "paper not found")
    try:
        return await run_in_threadpool(outline_feat.restore_pdf, paper_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


class LocateBody(BaseModel):
    text: str


@router.post("/{paper_id}/locate")
async def locate(paper_id: str, body: LocateBody):
    """Find where a snippet appears in the PDF → {page, rects} (for click-to-highlight)."""
    if not store.get_paper(paper_id):
        raise HTTPException(404, "paper not found")
    loc = await run_in_threadpool(ingest.locate_text, store.pdf_path(paper_id), body.text)
    return loc or {"page": None, "rects": []}


@router.get("/{paper_id}/tex")
async def get_tex(paper_id: str):
    """LaTeX source for an arXiv paper (cached). {available, files:[{name,tex}], main}."""
    p = store.get_paper(paper_id)
    if not p:
        raise HTTPException(404, "paper not found")
    arxiv_id = p.get("arxiv_id")
    if not arxiv_id:
        return {"available": False, "reason": "not an arXiv paper", "files": []}
    cached = store.cache_get(paper_id, "tex")
    if cached:
        return cached
    try:
        res = await importers.fetch_arxiv_tex(arxiv_id)
    except Exception as e:  # noqa: BLE001 — network/parse errors surface to the UI
        return {"available": False, "reason": f"could not fetch arXiv source: {e}", "files": []}
    out = {"available": bool(res["files"]), "main": res.get("main"), "files": res["files"]}
    if out["available"]:
        store.cache_set(paper_id, "tex", out)
    return out


@router.get("/{paper_id}/fulltext")
async def get_fulltext(paper_id: str):
    parsed = store.load_parsed(paper_id)
    if not parsed:
        raise HTTPException(404, "parsed data not found")
    return {"full_text": parsed["full_text"]}


@router.get("/{paper_id}/reading")
async def get_reading(paper_id: str, lang: str | None = None, force: bool = False):
    """The paper reflowed into a single reading column.

    The layout analysis reads every line of the PDF and asks it to locate every
    sentence, so it runs in a thread and is cached on disk afterwards (see
    ``pdf.reflow``). ``lang`` asks for the translations to be attached too.
    """
    if not annot_writer.target_path(paper_id).exists():
        raise HTTPException(404, "pdf not found")
    doc = await run_in_threadpool(lambda: reflow.build_reading_doc(paper_id, force=force))
    return reflow.attach_translations(doc, paper_id, lang)


@router.get("/{paper_id}/reading/figure/{name}")
async def get_reading_figure(paper_id: str, name: str):
    """A figure cropped out of the PDF for the reading view."""
    path = reflow.figure_file(paper_id, name)
    if path is None:
        raise HTTPException(404, "figure not found")
    return FileResponse(str(path), media_type="image/png")
