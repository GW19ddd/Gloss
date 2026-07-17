"""AI feature endpoints: summarize, explain, translate, auto-highlight, chat (SSE)."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..features import chat as chat_feat
from ..features import explain as explain_feat
from ..features import highlight as highlight_feat
from ..features import mindmap as mindmap_feat
from ..features import notes as notes_feat
from ..features import summarize as summarize_feat
from ..features import translate as translate_feat
from ..library import store

router = APIRouter(prefix="/api", tags=["ai"])


class Override(BaseModel):
    provider: str | None = None
    model: str | None = None
    language: str | None = None


class SummarizeBody(Override):
    refresh: bool = False


class ExplainBody(Override):
    paper_id: str | None = None
    selection: str
    context: str | None = None


class TranslateBody(Override):
    text: str | None = None
    paper_id: str | None = None
    page: int | None = None          # single page (0-based)
    page_start: int | None = None    # page range (0-based, inclusive)
    page_end: int | None = None


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatBody(Override):
    paper_id: str | None = None
    chat_id: str | None = None
    messages: list[ChatMessage]
    selection: str | None = None


@router.post("/papers/{paper_id}/summarize")
async def summarize(paper_id: str, body: SummarizeBody):
    if not store.get_paper(paper_id):
        raise HTTPException(404, "paper not found")
    try:
        return await summarize_feat.summarize_paper(
            paper_id, language=body.language, refresh=body.refresh,
            provider=body.provider, model=body.model,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/papers/{paper_id}/mindmap")
async def mindmap(paper_id: str, body: SummarizeBody):
    if not store.get_paper(paper_id):
        raise HTTPException(404, "paper not found")
    try:
        tree = await mindmap_feat.build_mindmap(
            paper_id, language=body.language, refresh=body.refresh,
            provider=body.provider, model=body.model,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"tree": tree}


@router.post("/papers/{paper_id}/notes")
async def notes(paper_id: str, body: SummarizeBody):
    if not store.get_paper(paper_id):
        raise HTTPException(404, "paper not found")
    try:
        md = await notes_feat.build_notes(
            paper_id, language=body.language, refresh=body.refresh,
            provider=body.provider, model=body.model,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"markdown": md}


@router.post("/explain")
async def explain(body: ExplainBody):
    if not body.selection.strip():
        raise HTTPException(400, "empty selection")
    text = await explain_feat.explain_selection(
        body.paper_id, body.selection, context=body.context,
        language=body.language, provider=body.provider, model=body.model,
    )
    return {"explanation": text}


@router.post("/translate")
async def translate(body: TranslateBody):
    # page range (from page_start to page_end, 0-based inclusive)
    if body.paper_id and body.page_start is not None:
        end = body.page_end if body.page_end is not None else body.page_start
        try:
            sents = await translate_feat.translate_range(
                body.paper_id, body.page_start, end, language=body.language,
                provider=body.provider, model=body.model,
            )
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"sentences": sents}
    # single page
    if body.paper_id and body.page is not None:
        try:
            sents = await translate_feat.translate_page(
                body.paper_id, body.page, language=body.language,
                provider=body.provider, model=body.model,
            )
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"sentences": sents}
    if body.text:
        out = await translate_feat.translate_text(
            body.text, language=body.language, provider=body.provider, model=body.model
        )
        return {"translation": out}
    raise HTTPException(400, "provide text, or paper_id + page")


@router.get("/papers/{paper_id}/translations")
async def get_translations(paper_id: str, lang: str | None = None):
    if not store.get_paper(paper_id):
        raise HTTPException(404, "paper not found")
    sents = translate_feat.get_translations(paper_id, language=lang)
    return {
        "sentences": sents,
        "pages": sorted({s["page"] for s in sents}),
    }


@router.post("/papers/{paper_id}/autohighlight")
async def autohighlight(paper_id: str, body: Override):
    if not store.get_paper(paper_id):
        raise HTTPException(404, "paper not found")
    try:
        items = await highlight_feat.auto_highlight(
            paper_id, provider=body.provider, model=body.model
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"highlights": items}


@router.post("/chat")
async def chat(body: ChatBody):
    messages = [m.model_dump() for m in body.messages]

    async def gen():
        acc = []
        try:
            async for delta in chat_feat.chat_stream(
                body.paper_id, messages, selection=body.selection,
                language=body.language, provider=body.provider, model=body.model,
            ):
                acc.append(delta)
                yield f"data: {json.dumps({'delta': delta})}\n\n"
        except Exception as e:  # surface errors to the client stream
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        else:
            # persist to chat history if a chat_id was supplied
            if body.chat_id and messages:
                try:
                    store.add_message(body.chat_id, "user", messages[-1]["content"])
                    store.add_message(body.chat_id, "assistant", "".join(acc))
                except Exception:
                    pass
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
