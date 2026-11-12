"""Zotero integration through Zotero's local HTTP API (http://localhost:23119).

Zotero has to be running and "Allow other applications on this computer to
communicate with Zotero" must be enabled (Settings → Advanced).

Requests must bypass any system proxy: this machine reaches the internet
through a proxy and httpx would happily send localhost through it, which fails
with an opaque "connection closed" error. See ``net.py``.

Two Zotero concepts matter here:
  * an *annotation* is a child of the **PDF attachment**,
  * Gloss exports its note as a **standalone item** of its own, not as a child
    note hanging off the paper, so the note never competes with the user's own
    child notes on that item.

Writing needs two things, both of them easy to get wrong (read from
``server_localAPI.js`` in Zotero's ``app/omni.ja``, not guessed):
  * a local API key from ``POST /api/local/authorize``, sent as
    ``Zotero-API-Key``. The endpoint opens a modal offering *Allow*,
    *Always Allow* and *Deny*. Only *Always Allow* yields a key that survives;
    *Allow* hands out a **single-use** key that the first successful write
    consumes, so a client must be ready to see a later 401 and reauthorize.
  * ``Zotero-Server-ID`` — required on writes (missing → 428), and it has to
    match the running instance (stale → 412). It changes when Zotero restarts.
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from . import config

BASE = "http://localhost:23119"
TIMEOUT = 6.0
# The authorize endpoint blocks until the user answers the modal in Zotero, so
# it cannot share the normal timeout.
AUTH_TIMEOUT = 300.0
APP_NAME = "Gloss"

# Colour and marker used for annotations Gloss creates, so they stay
# recognisable among the user's own highlights inside Zotero.
GLOSS_COLOR = "#ffd400"
GLOSS_MARK = "[Gloss]"

# Zotero reports the library id of the local ("my library") user; cached
# because every other call needs it.
_library_id: int | None = None

# Local API key and server id, both needed on every write. The key lives next
# to the config rather than inside it so it never reaches the browser through
# ``public_config()``.
_AUTH_PATH = config.DATA_DIR / "zotero_auth.json"
_api_key: str | None = None
_server_id: str | None = None


class NotAuthorized(RuntimeError):
    """Zotero refused a write because Gloss has no usable local API key."""


def _load_key() -> str | None:
    global _api_key
    if _api_key:
        return _api_key
    try:
        _api_key = json.loads(_AUTH_PATH.read_text("utf-8")).get("key") or None
    except (OSError, ValueError):
        _api_key = None
    return _api_key


def _save_key(key: str, remember: bool) -> None:
    global _api_key
    _api_key = key or None
    _AUTH_PATH.write_text(
        json.dumps({"key": _api_key, "remember": bool(remember)}, ensure_ascii=False),
        encoding="utf-8",
    )


def forget_key() -> None:
    """Drop a key that Zotero stopped accepting (single-use keys expire)."""
    global _api_key
    _api_key = None
    try:
        _AUTH_PATH.unlink()
    except OSError:
        pass


def authorized() -> bool:
    """Whether a key is on file. It may still be a spent single-use key."""
    return _load_key() is not None


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=BASE, timeout=TIMEOUT, trust_env=False)


def _norm(text: str) -> str:
    """Lower-case and collapse whitespace so quotes compare reliably."""
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def _first_author(paper: dict) -> str:
    authors = paper.get("authors") or []
    if isinstance(authors, str):
        try:
            authors = json.loads(authors)
        except ValueError:
            authors = [authors]
    return str(authors[0]) if authors else ""


# ---------------------------------------------------------------------------
# Connection status
# ---------------------------------------------------------------------------
async def ping() -> bool:
    """True when Zotero is running and its local API answers."""
    try:
        async with _client() as client:
            r = await client.get("/connector/ping")
    except httpx.HTTPError:
        return False
    return r.status_code == 200


async def server_id(refresh: bool = False) -> str | None:
    """Id of the running Zotero instance — only Zotero 10 and later send one.

    Its presence doubles as the write test: local write requests (POST/PUT/
    PATCH/DELETE) were added in Zotero 10, and older clients answer them with
    501 Not Implemented. Gloss therefore cannot create annotations on a Zotero
    that reports no server id, and the UI has to say so instead of silently
    handing out page-only links.

    Cached, because every write has to send it. Zotero answers 412 when the
    cached value is stale, which is the caller's cue to pass ``refresh=True``.
    """
    global _server_id
    if _server_id and not refresh:
        return _server_id
    try:
        async with _client() as client:
            r = await client.get("/api/")
    except httpx.HTTPError:
        _server_id = None
        return None
    _server_id = r.headers.get("Zotero-Server-ID")
    return _server_id


async def status() -> dict[str, Any]:
    """{running, library_id, library_name, writable, authorized, hint} — polled by the UI."""
    if not await ping():
        return {
            "running": False,
            "library_id": None,
            "library_name": None,
            "writable": False,
            "authorized": False,
            "hint": "Open Zotero and enable Settings → Advanced → "
            "'Allow other applications on this computer to communicate with Zotero'.",
        }
    uid = await user_id()
    writable = (await server_id()) is not None
    ok = authorized()
    hint = None if uid else "Zotero answered but the local API refused the request."
    if writable and uid and not ok:
        hint = (
            "Zotero will ask you to authorise Gloss once — "
            "pick 'Always Allow' so it keeps working."
        )
    return {
        "running": uid is not None,
        "library_id": uid,
        "library_name": "My Library" if uid else None,
        "writable": writable,
        "authorized": ok,
        "hint": hint,
    }


async def user_id() -> int | None:
    """Numeric id of the local library, used as ``/api/users/<id>``."""
    global _library_id
    if _library_id:
        return _library_id
    try:
        async with _client() as client:
            r = await client.get(
                "/api/users/0/items", params={"limit": 1, "format": "json"}
            )
            r.raise_for_status()
            items = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    if items:
        _library_id = (items[0].get("library") or {}).get("id")
    return _library_id


async def _api(path: str, params: dict | None = None) -> Any:
    async with _client() as client:
        r = await client.get(path, params={"format": "json", **(params or {})})
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Reading items
# ---------------------------------------------------------------------------
async def search(
    query: str, limit: int = 10, qmode: str = "everything"
) -> list[dict]:
    """Free-text search across the library; returns compact item summaries.

    ``qmode`` is not cosmetic. Zotero's default ``titleCreatorYear`` only looks
    at title, creators and year, so a DOI, an arXiv id or a file name can never
    match it — and those are exactly the keys Gloss matches papers by.
    ``everything`` searches all fields; the default mode stays available as a
    fallback for clients that ignore the parameter.
    """
    uid = await user_id()
    if not uid or not query.strip():
        return []
    try:
        raw = await _api(
            f"/api/users/{uid}/items",
            {"q": query.strip(), "limit": limit, "qmode": qmode},
        )
    except httpx.HTTPError:
        return []
    out = []
    for entry in raw or []:
        data = entry.get("data") or {}
        if data.get("itemType") in {"attachment", "note", "annotation"}:
            continue
        out.append(
            {
                "key": data.get("key"),
                "title": data.get("title") or "",
                "year": (data.get("date") or "")[:4],
                "authors": [
                    (c.get("lastName") or c.get("name") or "")
                    for c in (data.get("creators") or [])
                    if isinstance(c, dict)
                ][:3],
                "doi": data.get("DOI") or "",
                "itemType": data.get("itemType"),
            }
        )
    return out


async def children(item_key: str, item_type: str | None = None) -> list[dict]:
    """Child items (attachments / notes / annotations) of an item.

    Zotero only returns annotations when the request filters on
    ``itemType=annotation``; without it an attachment's children come back
    empty even though annotations exist.
    """
    uid = await user_id()
    if not uid:
        return []
    params = {"limit": 500}
    if item_type:
        params["itemType"] = item_type
    try:
        raw = await _api(f"/api/users/{uid}/items/{item_key}/children", params)
    except httpx.HTTPError:
        return []
    out = []
    for entry in raw or []:
        data = entry.get("data") or {}
        if item_type and data.get("itemType") != item_type:
            continue
        out.append(data)
    return out


async def pdf_attachments(item_key: str) -> list[dict]:
    """PDF attachments of a paper, including their Zotero path and link mode."""
    out = []
    for data in await children(item_key, "attachment"):
        if data.get("contentType") != "application/pdf":
            continue
        out.append(
            {
                "key": data.get("key"),
                "title": data.get("title") or "",
                "path": data.get("path") or "",
                "linkMode": data.get("linkMode"),
                "filename": (data.get("path") or "").rsplit("/", 1)[-1],
            }
        )
    return out


async def annotations(attachment_key: str) -> list[dict]:
    """Existing Zotero annotations under a PDF attachment."""
    out = []
    for data in await children(attachment_key, "annotation"):
        pos = data.get("annotationPosition")
        if isinstance(pos, str):
            try:
                pos = json.loads(pos)
            except ValueError:
                pos = {}
        pos = pos or {}
        out.append(
            {
                "key": data.get("key"),
                "type": data.get("annotationType"),
                "text": data.get("annotationText") or "",
                "comment": data.get("annotationComment") or "",
                "color": data.get("annotationColor") or "",
                "page": pos.get("pageIndex"),
                "rects": pos.get("rects") or [],
                "page_label": data.get("annotationPageLabel"),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Matching a Gloss paper to a Zotero item
# ---------------------------------------------------------------------------
async def search_all_modes(query: str, limit: int = 10) -> list[dict]:
    """Search under both quicksearch modes and merge the hits.

    Neither mode is a superset of the other: the default ``titleCreatorYear``
    never matches a DOI or an arXiv id, while ``everything`` can miss a single
    bare word that the default mode finds. Measured on a real library:
    ``10.48550/arXiv.2408.03095`` → only ``everything``; ``TestART`` → only
    ``titleCreatorYear``. Ask both or papers with a DOI stay unreachable.
    """
    merged: dict[str, dict] = {}
    for qmode in ("titleCreatorYear", "everything"):
        for item in await search(query, limit, qmode=qmode):
            merged.setdefault(item["key"], item)
    return list(merged.values())


def _repair_mojibake(text: str) -> str:
    """Undo UTF-8 bytes that were decoded as cp1252 / latin-1 upstream."""
    for encoding in ("cp1252", "latin-1"):
        try:
            candidate = text.encode(encoding).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        # A repair that leaves replacement chars behind made things worse.
        if candidate and "�" not in candidate:
            return candidate
    return text


def _title_queries(title: str) -> list[str]:
    """Search terms for a title that may really be a filename.

    Imported papers often carry ``作者 等 - 2025 - Real Title -side_by_side``,
    sometimes mojibake'd. Zotero's quicksearch matches none of that verbatim.
    """
    text = _repair_mojibake(title or "").strip()
    text = re.sub(r"[-_](dual|mono|side_by_side)$", "", text, flags=re.I)
    if text.lower().endswith(".pdf"):
        text = text[:-4]
    parts = [p.strip() for p in text.split(" - ") if p.strip()]
    # "Author 等 - 2025 - Title": everything up to the year is metadata.
    for index, part in enumerate(parts[:-1]):
        if re.fullmatch(r"(19|20)\d\d", part):
            parts = parts[index + 1:]
            break
    words = " ".join(parts).split()
    if not words:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for size in (12, 6, 4):
        probe = " ".join(words[:size]).strip(" ,:;-")
        if len(probe) >= 3 and probe.lower() not in seen:
            seen.add(probe.lower())
            out.append(probe)
    return out


async def _collect(paper: dict, source_pdf: str | None) -> dict[str, dict]:
    candidates: dict[str, dict] = {}

    async def _add(query: str, reason: str) -> None:
        for item in await search_all_modes(query):
            key = item["key"]
            if key and key not in candidates:
                item["reason"] = reason
                candidates[key] = item

    doi = (paper.get("doi") or "").strip()
    if doi:
        await _add(doi, "doi")
    arxiv_id = (paper.get("arxiv_id") or "").strip()
    if arxiv_id:
        await _add(arxiv_id, "arxiv")
    for probe in _title_queries(paper.get("title") or ""):
        await _add(probe, "title")
    if source_pdf:
        stem = source_pdf.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        # same cleanup as the title path, then use it as a filename probe
        for probe in _title_queries(stem):
            await _add(probe, "filename")
    return candidates


async def match_paper(paper: dict, source_pdf: str | None = None) -> list[dict]:
    """Candidate Zotero items for a Gloss paper, best guess first.

    Strategy: DOI → arXiv id → title (+year) → file name of the linked PDF,
    each searched under both quicksearch modes (see :func:`search_all_modes`).
    """
    candidates = await _collect(paper, source_pdf)

    out = list(candidates.values())
    for item in out:
        item["attachments"] = await pdf_attachments(item["key"])
    # prefer items that actually have a PDF attached
    out.sort(key=lambda i: (not i.get("attachments"), i.get("reason") != "doi"))
    return out[:8]


def pick_attachment(
    attachments: list[dict], source_pdf: str | None = None
) -> dict | None:
    """Choose which attachment a note should link to.

    Prefers an exact file-name match with the PDF Gloss is reading, then the
    original (a translated PDF carries a -dual/-mono/-side_by_side suffix).
    """
    if not attachments:
        return None
    if source_pdf:
        want = source_pdf.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
        for att in attachments:
            if att.get("filename", "").lower() == want:
                return att
    for att in attachments:
        if not re.search(r"-(dual|mono|side_by_side)\.pdf$", att.get("filename", ""), re.I):
            return att
    return attachments[0]


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------
async def authorize(app_name: str = APP_NAME) -> dict[str, Any]:
    """Ask Zotero for a local API key; blocks until the user answers the modal.

    Zotero only stores the key — and only skips this modal next time — when the
    user presses "Always Allow". A plain "Allow" key is spent by the first
    write, which is why :func:`_write` has to be ready for a 401.
    """
    sid = await server_id(refresh=True)
    if not sid:
        raise RuntimeError("Zotero is not answering its local API")
    try:
        async with httpx.AsyncClient(
            base_url=BASE, timeout=AUTH_TIMEOUT, trust_env=False
        ) as client:
            r = await client.post(
                "/api/local/authorize",
                json={"appName": app_name},
                headers={"Zotero-Server-ID": sid},
            )
    except httpx.HTTPError as e:
        raise RuntimeError(f"could not reach Zotero: {e}") from e
    if r.status_code != 200:
        raise RuntimeError(f"Zotero refused to authorise Gloss ({r.status_code})")
    body = r.json()
    if not body.get("key"):
        raise RuntimeError("Zotero denied the request")
    _save_key(body["key"], bool(body.get("remember")))
    return {"authorized": True, "remember": bool(body.get("remember"))}


async def _write(
    method: str, path: str, payload: Any, version: int | None = None
) -> dict[str, Any]:
    """Send a write request carrying both credentials.

    A 401 means the key is gone — an "Allow" key is consumed by the first write
    that uses it — so Gloss has to ask again rather than retry blindly. A 412
    means Zotero restarted and the cached server id went stale, which a refresh
    fixes on the spot.
    """
    uid = await user_id()
    if not uid:
        raise RuntimeError("Zotero is not reachable")
    full = f"/api/users/{uid}{path}"
    for _ in range(2):
        sid = await server_id()
        key = _load_key()
        if not sid or not key:
            raise NotAuthorized("Zotero has not authorised Gloss yet")
        async with _client() as client:
            r = await client.request(
                method,
                full,
                json=payload,
                headers={
                    "Zotero-Server-ID": sid,
                    "Zotero-API-Key": key,
                    # Zotero answers 428 unless an update names the version it
                    # is replacing.
                    **(
                        {"If-Unmodified-Since-Version": str(version)}
                        if version is not None
                        else {}
                    ),
                },
            )
        if r.status_code == 401:
            forget_key()
            raise NotAuthorized("Zotero no longer recognises the stored key")
        if r.status_code == 412:
            await server_id(refresh=True)
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"Zotero rejected the write ({r.status_code})")
        return r.json() if r.content else {}
    raise RuntimeError("Zotero rejected the write")


def _created_keys(res: dict[str, Any]) -> dict[str, str]:
    """Request index → created item key, out of a write response.

    Zotero 10's local API answers with ``successful`` holding
    ``{index: {key, version, ...}}``; the web API's ``success`` shape stays as
    a fallback.
    """
    out: dict[str, str] = {}
    for bucket in ("successful", "success"):
        for index, value in (res.get(bucket) or {}).items():
            if isinstance(value, dict):
                out[str(index)] = value.get("key")
            elif isinstance(value, str):
                out[str(index)] = value
    return out


async def _post_items(payload: list[dict]) -> dict[str, Any]:
    return await _write("POST", "/items", payload)


async def create_annotations(
    attachment_key: str, evidence: list[dict]
) -> list[dict]:
    """Turn note evidence into real Zotero highlight annotations.

    ``evidence`` items look like ``{id, quote, why, page, rects}`` with a
    0-based ``page`` (Gloss convention, same as Zotero's ``pageIndex``).
    Annotations that already exist (same page + same quote) are reused instead
    of duplicated. Returns one result per evidence item, in order.
    """
    existing = await annotations(attachment_key)
    by_identity = {
        (e.get("page"), _norm(e.get("text"))[:80]): e for e in existing
    }
    pending: list[tuple[int, dict]] = []
    results: dict[int, dict] = {}

    for i, ev in enumerate(evidence):
        page = ev.get("page")
        quote = ev.get("quote") or ""
        if page is None or not quote:
            results[i] = {"evidence_id": ev.get("id"), "key": None, "reused": False}
            continue
        identity = (page, _norm(quote)[:80])
        if identity in by_identity:
            results[i] = {
                "evidence_id": ev.get("id"),
                "key": by_identity[identity]["key"],
                "reused": True,
            }
            continue
        why = (ev.get("why") or "").strip()
        pending.append(
            (
                i,
                {
                    "itemType": "annotation",
                    "parentItem": attachment_key,
                    "annotationType": "highlight",
                    "annotationText": quote,
                    "annotationComment": f"{GLOSS_MARK} {why}".strip(),
                    "annotationColor": GLOSS_COLOR,
                    "annotationPosition": json.dumps(
                        {"pageIndex": page, "rects": ev.get("rects") or []},
                        ensure_ascii=False,
                    ),
                },
            )
        )

    if pending:
        try:
            res = await _post_items([payload for _, payload in pending])
        except (httpx.HTTPError, NotAuthorized) as e:
            for i, _ in pending:
                results[i] = {
                    "evidence_id": evidence[i].get("id"),
                    "key": None,
                    "reused": False,
                    "error": str(e),
                }
            return [results[i] for i in range(len(evidence))]
        created = _created_keys(res)
        failed = res.get("failed") or {}
        for offset, (i, _) in enumerate(pending):
            key = created.get(str(offset))
            results[i] = {
                "evidence_id": evidence[i].get("id"),
                "key": key,
                "reused": False,
                "error": str(failed[str(offset)]) if str(offset) in failed else None,
            }
    for i, ev in enumerate(evidence):
        # keep page/why on the result so callers can build the zotero:// link
        results[i]["page"] = ev.get("page")
        results[i]["why"] = ev.get("why") or ""
    return [results[i] for i in range(len(evidence))]


async def resolve_annotations(
    attachment_key: str, evidence: list[dict]
) -> list[dict]:
    """Match note evidence against annotations Zotero already has.

    The local API is read-only, so Gloss cannot create annotations itself. It
    looks for an existing annotation on the same page with the same text instead
    — that covers highlights made inside Zotero and highlights Zotero imported
    from the PDF — and links to those. Anything unmatched still gets a
    page-accurate link.
    """
    existing = await annotations(attachment_key)
    exact: dict[tuple[Any, str], dict] = {}
    for a in existing:
        exact.setdefault((a.get("page"), _norm(a.get("text"))[:80]), a)
    results = []
    for ev in evidence:
        page = ev.get("page")
        quote = ev.get("quote") or ""
        hit = None
        if page is not None and quote:
            hit = exact.get((page, _norm(quote)[:80]))
            if not hit:
                # Text extraction differs slightly between readers, so fall back
                # to a containment check on the same page.
                needle = _norm(quote)[:60]
                if needle:
                    hit = next(
                        (
                            a
                            for a in existing
                            if a.get("page") == page and needle in _norm(a.get("text"))
                        ),
                        None,
                    )
        results.append(
            {
                "evidence_id": ev.get("id"),
                "key": hit["key"] if hit else None,
                "page": page,
                "why": ev.get("why") or "",
                "matched": bool(hit),
            }
        )
    return results


def note_html(html: str) -> str:
    """Wrap note HTML the way Zotero stores it.

    Zotero rejects bare HTML with a 400: every note lives inside a
    ``<div data-schema-version="9">`` container.
    """
    body = (html or "").strip()
    if body.startswith("<div data-schema-version"):
        return body
    return f'<div data-schema-version="9">{body}</div>'


async def item_version(item_key: str) -> int | None:
    """Current version of an item, required to update or delete it."""
    if not item_key:
        return None
    uid = await user_id()
    if not uid:
        return None
    try:
        data = await _api(f"/api/users/{uid}/items/{item_key}")
    except httpx.HTTPError:
        return None
    return (data.get("data") or {}).get("version")


async def note_parent(note_key: str) -> str | None:
    """Which item a note hangs under (None for a note at the library root)."""
    if not note_key:
        return None
    uid = await user_id()
    if not uid:
        return None
    try:
        data = await _api(f"/api/users/{uid}/items/{note_key}")
    except httpx.HTTPError:
        return None
    return (data.get("data") or {}).get("parentItem")


async def put_note(
    html: str, note_key: str | None = None, parent: str | None = None
) -> dict:
    """Create a note under ``parent`` (or standalone), or overwrite one by key.

    Notes live as children of the paper: opening the item is where a reader
    looks, and Zotero shows the note's first line as its title.
    """
    payload = note_html(html)
    if note_key:
        # An update replaces the whole item: leaving parentItem out moves the
        # note back to the library root.
        current = parent or await note_parent(note_key)
        item: dict = {"itemType": "note", "note": payload}
        if current:
            item["parentItem"] = current
        await _write(
            "PUT", f"/items/{note_key}", item, version=await item_version(note_key)
        )
        return {"key": note_key, "updated": True}
    item: dict = {"itemType": "note", "note": payload}
    if parent:
        item["parentItem"] = parent
    data = await _write("POST", "/items", [item])
    return {
        "key": _created_keys(data).get("0"),
        "updated": False,
        "failed": data.get("failed") or {},
    }


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------
def open_pdf_url(
    attachment_key: str, page: int | None = None, annotation_key: str | None = None
) -> str:
    """``zotero://open-pdf`` link; ``page`` is 1-based as Zotero expects."""
    if not attachment_key:
        return ""
    url = f"zotero://open-pdf/library/items/{attachment_key}"
    query = []
    if page is not None:
        query.append(f"page={int(page) + 1}")
    if annotation_key:
        query.append(f"annotation={annotation_key}")
    return url + ("?" + "&".join(query) if query else "")


def select_url(item_key: str) -> str:
    """Link that selects the item in Zotero's library pane."""
    return f"zotero://select/library/items/{item_key}"
