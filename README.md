# 🌙 Moonlight-Local

A **local, self-hosted paper-reading tool** in the style of [Moonlight](https://www.themoonlight.io/) —
an AI colleague for reading research papers. The AI backend defaults to your **local `claude` CLI**
(subscription auth — no API key, used just like the Claude terminal), and can also point at any
**Anthropic** or **OpenAI-compatible** API. It can **load Claude/Codex skills** and run them against
the paper you're reading.

Everything runs on your machine: a FastAPI backend serves a browser PDF reader with an AI side panel.

## Features (all of Moonlight's, locally)

| Feature | What it does |
|---|---|
| 📖 **PDF reader** | PDF.js viewer with real text selection; select text → popover actions |
| 🧠 **Summary** | 3-sentence TL;DR + problem / method / results / contributions / 5-min key points / limitations |
| 💡 **Explain** | Explain a selected equation / table / term in context (LaTeX rendered via KaTeX) |
| 🌐 **Translate** | Context-aware translation of a selection, or a whole page **side-by-side** (default 中文) |
| 💬 **Chat** | Ask questions like a colleague — grounded in the paper via BM25 retrieval, streamed |
| ✨ **Auto-highlight** | AI marks key sentences (contribution / method / result / limitation / …) directly on the PDF |
| ✍️ **Markup** | Your own highlights (5 colors) + notes, anchored to the page and saved |
| 🔗 **References** | Parse the bibliography, resolve & enrich via Crossref/arXiv, one-click links |
| 🔭 **Scholar search** | Find related papers (Semantic Scholar / arXiv) and import them |
| 📚 **Library** | Import by arXiv id / URL / DOI or upload PDFs; organized, searchable |
| 🧩 **Skills** | Load skills from Claude (`~/.claude/skills`, plugins) & Codex (`$CODEX_HOME/skills`), run on the paper |
| ⚡ **Providers** | local claude CLI (default) · Anthropic API · any OpenAI-compatible endpoint |

## Quick start

```bash
cd /home/cjc/moonlight        # (symlink to /root/autodl-tmp/cjc/moonlight)
scripts/setup.sh              # backend venv + deps, frontend build  (first time)
scripts/run.sh                # → http://<host>:8010
```

Open the URL in a browser. On AutoDL, map port **8010** to the 6006 custom-service slot, or forward it
over SSH: `ssh -L 8010:127.0.0.1:8010 <server>`.

Then: paste an arXiv id (e.g. `1706.03762`) or upload a PDF, click the card, and read.

## CLI

```bash
./moonlight serve                 # start the web app
./moonlight open 1706.03762       # import + serve + open browser
./moonlight import paper.pdf      # add a local PDF / arXiv / DOI to the library
./moonlight ls                    # list library
./moonlight summarize 1706.03762  # print a summary in the terminal
./moonlight chat <paper_id>       # interactive terminal chat (claude-style)
./moonlight skills                # list discovered Claude/Codex skills
```

## Choosing the AI provider

The **Settings** tab (or `backend/data/config.json`) selects the provider:

- **local_claude** (default) — uses the `claude` CLI on this machine; no API key. Model: `sonnet`/`opus`/…
- **anthropic** — set an API key + model (`claude-…`).
- **openai** — set `base_url` + key. Works with real OpenAI, a local vLLM, or the existing
  claude proxy at `http://127.0.0.1:8899/v1`.

## Architecture

```
backend/   FastAPI app
  app/providers/   local_claude · anthropic · openai · registry   (LLM abstraction)
  app/pdf/         PyMuPDF ingest (blocks+bboxes) + structure heuristics
  app/features/    summarize · explain · translate · chat(RAG) · highlight · citations
  app/search/      scholar search / recommend
  app/skills/      Claude/Codex SKILL.md discovery + runner
  app/library/     SQLite store + importers (arXiv/DOI/PDF) + service
  app/routers/     papers · ai · citations · scholar · annotations · skills · settings
frontend/  React + Vite + pdfjs-dist + KaTeX  (built to frontend/dist, served by the backend)
cli/       moonlight.py            scripts/  setup.sh · run.sh · dev.sh
```

See `CLAUDE.md` for the deeper design notes (LLM isolation, the network proxy, coordinate mapping).

## Notes

- The local `claude` CLI is run under an isolated `HOME` so it does **not** pick up your personal
  `~/.claude/CLAUDE.md` / memory — paper answers stay about the paper.
- External lookups (references, scholar) route through the machine's HTTP proxy and **degrade
  gracefully** to locally-parsed data when offline.
- All heavy artefacts (venv, node_modules, papers, DB) live on the data disk `/root/autodl-tmp`.
