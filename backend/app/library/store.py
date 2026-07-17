"""SQLite-backed library store + per-paper filesystem storage.

DB holds paper metadata, highlights/annotations, chats/messages, parsed references
and a small feature cache. Large artefacts (original.pdf, parsed.json) live under
``data/papers/<id>/`` on the data disk.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ..config import DB_PATH, PAPERS_DIR

_SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id TEXT PRIMARY KEY,
    title TEXT,
    authors TEXT,
    year TEXT,
    abstract TEXT,
    source TEXT,
    arxiv_id TEXT,
    doi TEXT,
    n_pages INTEGER,
    tags TEXT DEFAULT '[]',
    added_at REAL
);
CREATE TABLE IF NOT EXISTS highlights (
    id TEXT PRIMARY KEY,
    paper_id TEXT,
    page INTEGER,
    rects TEXT,
    color TEXT,
    category TEXT,
    text TEXT,
    note TEXT,
    kind TEXT,
    created_at REAL
);
CREATE TABLE IF NOT EXISTS chats (
    id TEXT PRIMARY KEY,
    paper_id TEXT,
    title TEXT,
    created_at REAL
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    chat_id TEXT,
    role TEXT,
    content TEXT,
    created_at REAL
);
CREATE TABLE IF NOT EXISTS refs (
    id TEXT PRIMARY KEY,
    paper_id TEXT,
    idx INTEGER,
    raw TEXT,
    title TEXT,
    authors TEXT,
    year TEXT,
    doi TEXT,
    arxiv_id TEXT,
    url TEXT,
    abstract TEXT,
    resolved INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS cache (
    paper_id TEXT,
    key TEXT,
    value TEXT,
    updated_at REAL,
    PRIMARY KEY (paper_id, key)
);
"""


def _now() -> float:
    return time.time()


def _uid() -> str:
    return uuid.uuid4().hex[:12]


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db() -> None:
    with _conn() as con:
        con.executescript(_SCHEMA)


# ---------------------------------------------------------------------------
# Papers
# ---------------------------------------------------------------------------
def paper_dir(paper_id: str) -> Path:
    d = PAPERS_DIR / paper_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def pdf_path(paper_id: str) -> Path:
    return paper_dir(paper_id) / "original.pdf"


def parsed_path(paper_id: str) -> Path:
    return paper_dir(paper_id) / "parsed.json"


def load_parsed(paper_id: str) -> dict | None:
    p = parsed_path(paper_id)
    if p.exists():
        return json.loads(p.read_text())
    return None


def save_parsed(paper_id: str, parsed: dict) -> None:
    parsed_path(paper_id).write_text(json.dumps(parsed, ensure_ascii=False))


def create_paper(meta: dict[str, Any]) -> str:
    pid = meta.get("id") or _uid()
    with _conn() as con:
        con.execute(
            """INSERT INTO papers (id,title,authors,year,abstract,source,arxiv_id,doi,n_pages,tags,added_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                pid,
                meta.get("title", ""),
                json.dumps(meta.get("authors", []), ensure_ascii=False),
                str(meta.get("year", "") or ""),
                meta.get("abstract", ""),
                meta.get("source", "upload"),
                meta.get("arxiv_id", ""),
                meta.get("doi", ""),
                int(meta.get("n_pages", 0) or 0),
                json.dumps(meta.get("tags", []), ensure_ascii=False),
                _now(),
            ),
        )
    return pid


def _row_to_paper(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["authors"] = json.loads(d.get("authors") or "[]")
    d["tags"] = json.loads(d.get("tags") or "[]")
    return d


def get_paper(paper_id: str) -> dict | None:
    with _conn() as con:
        r = con.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
        return _row_to_paper(r) if r else None


def list_papers() -> list[dict]:
    with _conn() as con:
        rows = con.execute("SELECT * FROM papers ORDER BY added_at DESC").fetchall()
        return [_row_to_paper(r) for r in rows]


def update_paper(paper_id: str, fields: dict[str, Any]) -> None:
    allowed = {"title", "authors", "year", "abstract", "tags", "doi", "arxiv_id"}
    sets, vals = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k in ("authors", "tags"):
            v = json.dumps(v, ensure_ascii=False)
        sets.append(f"{k}=?")
        vals.append(v)
    if not sets:
        return
    vals.append(paper_id)
    with _conn() as con:
        con.execute(f"UPDATE papers SET {','.join(sets)} WHERE id=?", vals)


def delete_paper(paper_id: str) -> None:
    with _conn() as con:
        for t in ("papers", "highlights", "chats", "messages", "refs", "cache"):
            col = "id" if t == "papers" else "paper_id"
            if t == "messages":
                con.execute(
                    "DELETE FROM messages WHERE chat_id IN (SELECT id FROM chats WHERE paper_id=?)",
                    (paper_id,),
                )
                continue
            con.execute(f"DELETE FROM {t} WHERE {col}=?", (paper_id,))
    d = PAPERS_DIR / paper_id
    if d.exists():
        for f in d.iterdir():
            f.unlink()
        d.rmdir()


# ---------------------------------------------------------------------------
# Highlights / annotations
# ---------------------------------------------------------------------------
def add_highlight(paper_id: str, h: dict) -> dict:
    hid = h.get("id") or _uid()
    row = (
        hid, paper_id, int(h.get("page", 0)),
        json.dumps(h.get("rects", [])),
        h.get("color", "#ffd54f"),
        h.get("category", ""),
        h.get("text", ""),
        h.get("note", ""),
        h.get("kind", "user"),
        _now(),
    )
    with _conn() as con:
        con.execute(
            """INSERT OR REPLACE INTO highlights
               (id,paper_id,page,rects,color,category,text,note,kind,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            row,
        )
    return get_highlight(hid)


def get_highlight(hid: str) -> dict | None:
    with _conn() as con:
        r = con.execute("SELECT * FROM highlights WHERE id=?", (hid,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["rects"] = json.loads(d.get("rects") or "[]")
    return d


def list_highlights(paper_id: str, kind: str | None = None) -> list[dict]:
    q = "SELECT * FROM highlights WHERE paper_id=?"
    args: list[Any] = [paper_id]
    if kind:
        q += " AND kind=?"
        args.append(kind)
    q += " ORDER BY page, created_at"
    with _conn() as con:
        rows = con.execute(q, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["rects"] = json.loads(d.get("rects") or "[]")
        out.append(d)
    return out


def update_highlight(hid: str, fields: dict) -> dict | None:
    allowed = {"color", "note", "category", "text"}
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    if sets:
        vals.append(hid)
        with _conn() as con:
            con.execute(f"UPDATE highlights SET {','.join(sets)} WHERE id=?", vals)
    return get_highlight(hid)


def delete_highlight(hid: str) -> None:
    with _conn() as con:
        con.execute("DELETE FROM highlights WHERE id=?", (hid,))


def clear_auto_highlights(paper_id: str) -> None:
    with _conn() as con:
        con.execute("DELETE FROM highlights WHERE paper_id=? AND kind='auto'", (paper_id,))


# ---------------------------------------------------------------------------
# Chats / messages
# ---------------------------------------------------------------------------
def create_chat(paper_id: str, title: str = "Chat") -> dict:
    cid = _uid()
    with _conn() as con:
        con.execute(
            "INSERT INTO chats (id,paper_id,title,created_at) VALUES (?,?,?,?)",
            (cid, paper_id, title, _now()),
        )
    return {"id": cid, "paper_id": paper_id, "title": title}


def list_chats(paper_id: str) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM chats WHERE paper_id=? ORDER BY created_at DESC", (paper_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def delete_chat(chat_id: str) -> None:
    with _conn() as con:
        con.execute("DELETE FROM messages WHERE chat_id=?", (chat_id,))
        con.execute("DELETE FROM chats WHERE id=?", (chat_id,))


def add_message(chat_id: str, role: str, content: str) -> dict:
    mid = _uid()
    with _conn() as con:
        con.execute(
            "INSERT INTO messages (id,chat_id,role,content,created_at) VALUES (?,?,?,?,?)",
            (mid, chat_id, role, content, _now()),
        )
    return {"id": mid, "chat_id": chat_id, "role": role, "content": content}


def list_messages(chat_id: str) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM messages WHERE chat_id=? ORDER BY created_at", (chat_id,)
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------
def set_refs(paper_id: str, refs: list[dict]) -> None:
    with _conn() as con:
        con.execute("DELETE FROM refs WHERE paper_id=?", (paper_id,))
        for i, r in enumerate(refs):
            con.execute(
                """INSERT INTO refs
                   (id,paper_id,idx,raw,title,authors,year,doi,arxiv_id,url,abstract,resolved)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    _uid(), paper_id, r.get("idx", i), r.get("raw", ""),
                    r.get("title", ""), json.dumps(r.get("authors", []), ensure_ascii=False),
                    str(r.get("year", "") or ""), r.get("doi", ""), r.get("arxiv_id", ""),
                    r.get("url", ""), r.get("abstract", ""), int(bool(r.get("resolved", 0))),
                ),
            )


def get_refs(paper_id: str) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM refs WHERE paper_id=? ORDER BY idx", (paper_id,)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["authors"] = json.loads(d.get("authors") or "[]")
        out.append(d)
    return out


def update_ref(ref_id: str, fields: dict) -> None:
    allowed = {"title", "authors", "year", "doi", "arxiv_id", "url", "abstract", "resolved"}
    sets, vals = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "authors":
            v = json.dumps(v, ensure_ascii=False)
        if k == "resolved":
            v = int(bool(v))
        sets.append(f"{k}=?")
        vals.append(v)
    if not sets:
        return
    vals.append(ref_id)
    with _conn() as con:
        con.execute(f"UPDATE refs SET {','.join(sets)} WHERE id=?", vals)


# ---------------------------------------------------------------------------
# Feature cache (summaries, translations, etc.)
# ---------------------------------------------------------------------------
def cache_get(paper_id: str, key: str) -> Any | None:
    with _conn() as con:
        r = con.execute(
            "SELECT value FROM cache WHERE paper_id=? AND key=?", (paper_id, key)
        ).fetchone()
    return json.loads(r["value"]) if r else None


def cache_set(paper_id: str, key: str, value: Any) -> None:
    with _conn() as con:
        con.execute(
            "INSERT OR REPLACE INTO cache (paper_id,key,value,updated_at) VALUES (?,?,?,?)",
            (paper_id, key, json.dumps(value, ensure_ascii=False), _now()),
        )
