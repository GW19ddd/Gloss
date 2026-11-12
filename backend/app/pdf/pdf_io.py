"""Open / save helpers shared by everything that writes into a paper's PDF.

Both the highlight mirror and the outline writer need the same three things: a
process-wide lock, a forgiving ``open`` that yields ``None`` instead of raising
on an unusable file, and an append-only save that keeps unrelated PDF content
intact.
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import fitz  # PyMuPDF

# PDFs live on the data disk; two requests touching the same file at once would
# otherwise interleave open + incremental-save and corrupt it.
lock = threading.RLock()


@contextmanager
def open_path(path: Path) -> Iterator[fitz.Document | None]:
    """Yield the PDF at ``path`` opened for editing, or ``None`` if unusable."""
    if not path.exists() or path.stat().st_size == 0:
        yield None
        return
    try:
        doc = fitz.open(str(path))
    except Exception:
        yield None
        return
    try:
        if doc.needs_pass and not doc.authenticate(""):
            yield None
            return
        yield doc
    finally:
        doc.close()


def save(doc: fitz.Document) -> None:
    """Incremental save (append-only). Falls back to a full rewrite."""
    path = Path(doc.name)
    try:
        doc.saveIncr()
        return
    except Exception:
        pass
    # Some files (heavily repaired / object-stream-only PDFs) refuse an
    # incremental update. Rewrite them once instead of losing the edit.
    tmp = path.with_name(path.name + ".tmp")
    try:
        doc.save(str(tmp), garbage=0, deflate=True, encryption=fitz.PDF_ENCRYPT_KEEP)
        os.replace(str(tmp), str(path))
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
