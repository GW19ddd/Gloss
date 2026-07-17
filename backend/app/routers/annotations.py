"""User highlights + annotations (markup tools) and chat-history CRUD."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..library import store

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
    return h


@router.patch("/highlights/{hid}")
async def patch_highlight(hid: str, body: HighlightPatch):
    h = store.update_highlight(hid, body.model_dump(exclude_none=True))
    if not h:
        raise HTTPException(404, "highlight not found")
    return h


@router.delete("/highlights/{hid}")
async def delete_highlight(hid: str):
    store.delete_highlight(hid)
    return {"ok": True}


# ---- chat history ----
class ChatCreate(BaseModel):
    title: str = "Chat"


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
