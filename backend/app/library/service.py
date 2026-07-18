"""Glue: turn PDF bytes + metadata into a stored, parsed paper."""
from __future__ import annotations

import os
import re
import tempfile

from . import store
from ..pdf import ingest as pdf_ingest
from ..pdf import structure
from ..platform_support import run_in_process_with_timeout


def _parse_pdf_bytes(pdf_bytes: bytes) -> dict:
    fd, temp_path = tempfile.mkstemp(prefix="gloss-import-", suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as temp_file:
            temp_file.write(pdf_bytes)
        parsed = pdf_ingest.ingest_pdf(temp_path)
        parsed["sections"] = structure.detect_sections(parsed)
        return parsed
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


def parse_pdf_bytes_with_timeout(pdf_bytes: bytes, timeout: float) -> dict:
    """Parse an imported PDF outside the server process so timeout is enforceable."""
    return run_in_process_with_timeout(_parse_pdf_bytes, (pdf_bytes,), timeout)


def create_from_pdf_bytes(
    pdf_bytes: bytes, meta: dict, parsed: dict | None = None
) -> dict:
    """Persist a PDF, parse it, detect structure, seed references. Returns paper dict."""
    if pdf_bytes[:5] != b"%PDF-":
        raise ValueError("Not a PDF file")

    pid = store.create_paper({**meta, "n_pages": 0})
    try:
        store.pdf_path(pid).write_bytes(pdf_bytes)

        if parsed is None:
            parsed = pdf_ingest.ingest_pdf(store.pdf_path(pid))
            parsed["sections"] = structure.detect_sections(parsed)
        store.save_parsed(pid, parsed)

        # backfill title / authors if the importer didn't provide them
        fields: dict = {"n_pages": parsed["n_pages"]}
        if not meta.get("title"):
            fields["title"] = parsed["meta"].get("title") or _guess_title(parsed) or "Untitled"
        if not meta.get("authors"):
            author_str = parsed["meta"].get("author", "")
            if author_str:
                parts = re.split(r"\s*(?:,|;| and )\s*", author_str)
                fields["authors"] = [a.strip() for a in parts if a.strip()]
        store.update_paper(pid, fields)
        # keep n_pages in the papers row
        with store._conn() as con:  # noqa: SLF001 - internal helper reuse
            con.execute("UPDATE papers SET n_pages=? WHERE id=?", (parsed["n_pages"], pid))

        # seed raw reference entries (resolution happens on demand)
        ref_text = structure.find_references_text(parsed)
        entries = structure.split_reference_entries(ref_text)
        if entries:
            store.set_refs(pid, [{"idx": i, "raw": e} for i, e in enumerate(entries)])

        return store.get_paper(pid)
    except Exception:
        # A failed parse/write must not leave a zero-page row or orphaned PDF.
        try:
            store.delete_paper(pid)
        except Exception:
            pass
        raise


def _guess_title(parsed: dict) -> str:
    """Heuristic: the largest text block near the top of page 1."""
    pages = parsed.get("pages") or []
    if not pages:
        return ""
    blocks = pages[0]["blocks"]
    top = [b for b in blocks if b["bbox"][1] < pages[0]["height"] * 0.4]
    if not top:
        return ""
    best = max(top, key=lambda b: b["size"])
    line = best["text"].splitlines()[0] if best["text"] else ""
    return line.strip()[:200]
