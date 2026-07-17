# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Gloss (旁注) — a self-hosted clone of Moonlight (themoonlight.io), an "AI colleague for
reading research papers". A FastAPI backend serves a React/PDF.js reader UI and drives an LLM that
defaults to the **local `claude` CLI** (subscription auth, no API key) but can also use any
Anthropic or OpenAI-compatible endpoint. It can also load and run Claude/Codex **skills** against
the open paper.

## Location & disk (important)

- The project physically lives on the **data disk**: `/root/autodl-tmp/cjc/moonlight`.
  `/home/cjc/moonlight` is a **symlink** to it (the system disk `/` is ~91% full — keep
  `node_modules`, `.venv`, and `backend/data/` on the data disk).
- pip cache → `/root/autodl-tmp/.pip_cache`, npm cache → `/root/autodl-tmp/.npm-cache`. `scripts/setup.sh`
  pins these; do the same for any new install step.

## Commands

```bash
scripts/setup.sh            # create backend venv + install; npm install + vite build
scripts/run.sh              # serve web app (built frontend + API) on :8010 (0.0.0.0)
scripts/dev.sh              # dev: uvicorn --reload :8010 + vite dev :5173 (proxies /api)
./gloss <cmd>           # CLI: serve | open <src> | import <src> | ls | summarize <id|pdf|arxiv> | chat <id> | skills

# manual backend run
cd backend && .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8010
# rebuild frontend after UI changes (backend serves frontend/dist)
cd frontend && npm run build
```

Ports: `GLOSS_PORT` (default 8010), `GLOSS_HOST` (default 0.0.0.0). On AutoDL, map to the
6006 custom-service port or use SSH forwarding to reach it from a browser.

There is no test suite; verify by driving the API (upload a PDF → summarize/chat/etc.) or the CLI.

## Architecture (big picture)

**One FastAPI process** (`backend/app/main.py`) mounts all `/api/*` routers and, if
`frontend/dist` exists, serves the built SPA (catch-all route → `index.html`, `/assets` mounted).

**LLM provider abstraction** (`backend/app/providers/`) is the spine — everything LLM goes through
`providers/registry.py` (`complete()` / `stream()`), which picks a provider from `data/config.json`:
- `local_claude.py` — **default**. Shells out to `claude -p --output-format json --tools "" --model <m>`
  (system prompt via `--system-prompt-file`, conversation via stdin). Lifted from
  `/root/autodl-tmp/paperbench/claude_proxy/server.py`. Streaming uses `--output-format stream-json`.
  **Critical:** it runs under a sandbox `HOME` (`.claude-home/`, see `config.ensure_claude_sandbox`)
  that symlinks ONLY the auth files — otherwise the CLI auto-loads the user's `~/.claude/CLAUDE.md` +
  memory and leaks unrelated instructions into paper answers. Do not remove this isolation.
- `anthropic_api.py` / `openai_api.py` — httpx to the respective APIs. The OpenAI one also works
  against any OpenAI-compatible endpoint (e.g. the local claude_proxy at `http://127.0.0.1:8899/v1`).

**External network** (arXiv / Crossref / Semantic Scholar) must go through `backend/app/net.py`'s
`external_client()`. The box only reaches the internet via the **HTTP proxy** (`HTTPS_PROXY`);
`ALL_PROXY` is socks5h which httpx can't use without `socksio`. `external_client()` selects the
HTTP proxy and sets `trust_env=False`; provider clients that call localhost also use `trust_env=False`
so they are NOT proxied. Every external feature degrades gracefully to local data if a host is down.

**PDF pipeline** (`backend/app/pdf/`): `ingest.py` (PyMuPDF → per-page text blocks with **bounding
boxes** + page sizes; these anchor highlights to PDF.js coordinates) and `structure.py` (heuristic
sections / references / sentence splitting — no ML, offline-friendly). `locate_text()` maps a
sentence back to page rects for auto-highlighting.

**Features** (`backend/app/features/`, exposed via `routers/ai.py`, `citations.py`, `scholar.py`):
summarize, explain, translate (text + side-by-side page), chat (BM25 retrieval in `retrieval.py` +
SSE stream), auto-highlight (LLM picks sentences → `locate_text` → colored rects), citations
(LLM-parse references then Crossref enrich). Structured outputs use `features/common.json_complete`
(appends a JSON-shape instruction and tolerant-parses via `json_utils.extract_json`).

**Library** (`backend/app/library/`): SQLite (`store.py`, tables: papers/highlights/chats/messages/
refs/cache) + per-paper files under `backend/data/papers/<id>/{original.pdf,parsed.json}`.
`importers.py` fetches arXiv/DOI/PDF-URL; `service.create_from_pdf_bytes` is the ingest→store glue.

**Skills** (`backend/app/skills/loader.py`): globs `**/SKILL.md` under Claude dirs (`~/.claude/skills`,
project `.claude/skills`, plugins) and Codex (`$CODEX_HOME/skills`), plus `commands/*.md`; parses YAML
frontmatter. `routers/skills.py` runs a skill by injecting its body (`$ARGUMENTS` substituted +
current-paper context) as the prompt. The client sends a skill **id** (never a path) — only
discovered skills can run.

**Frontend** (`frontend/src/`): Vite + React + TS + `pdfjs-dist` + KaTeX, state in `store.ts`
(zustand). `pdf/PdfViewer.tsx` renders pages to canvas with a **manual text layer** (selectable
spans positioned from `getTextContent`) and a highlight overlay (rects in PDF points × render scale).
Text selection → `SelectionPopover` → `runSelectionAction` routes to the Explain/Translate/Chat tab.
`api/client.ts` has typed fetch wrappers + `streamPost` (POST-based SSE reader, since EventSource
can't POST). The pdf worker is bundled locally (no CDN) for offline use.

## Conventions / gotchas

- Coordinate system: PyMuPDF block bboxes and pdf.js viewports are both top-left origin in PDF
  points, so `pixel = point * scale`. Highlights rely on this — keep bbox values in PDF points.
- When killing the dev server, do NOT `pkill -f "uvicorn app.main:app"` — the pattern matches the
  killing shell's own command line. Kill by PID (from the port) instead.
- `data/config.json` holds API keys; it's gitignored (whole `backend/data/`). Settings API masks keys.
