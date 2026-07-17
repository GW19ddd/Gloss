"""Skill endpoints: list discovered Claude/Codex skills; run one on a paper."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..features.chat import _build_context
from ..providers import registry
from ..skills import loader

router = APIRouter(prefix="/api/skills", tags=["skills"])


class RunSkillBody(BaseModel):
    skill_id: str
    arguments: str = ""
    paper_id: str | None = None
    selection: str | None = None
    provider: str | None = None
    model: str | None = None


@router.get("")
async def list_skills():
    skills = loader.discover_skills()
    return {"skills": skills, "count": len(skills)}


def _lookup(skill_id: str) -> dict | None:
    for s in loader.discover_skills():
        if s["id"] == skill_id:
            return s
    return None


@router.post("/run")
async def run_skill(body: RunSkillBody):
    skill = _lookup(body.skill_id)
    if not skill:
        raise HTTPException(404, "skill not found")
    _, skill_body = loader.load_skill_body(skill["path"])

    args = body.arguments or ""
    instructions = skill_body.replace("$ARGUMENTS", args)

    context = ""
    if body.paper_id:
        context = _build_context(body.paper_id, args or skill["name"])
    if body.selection:
        context += f"\n\n[Selected text]:\n{body.selection}"

    system = (
        f"You are running the '{skill['name']}' skill inside Moonlight, a paper reader. "
        f"Follow these skill instructions faithfully:\n\n{instructions}"
    )
    if context:
        system += f"\n\n# Current paper context\n{context}"

    user = args or f"Run the '{skill['name']}' skill on the current paper."

    async def gen():
        try:
            async for delta in registry.stream(
                system, [{"role": "user", "content": user}],
                provider=body.provider, model=body.model,
            ):
                yield f"data: {json.dumps({'delta': delta})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
