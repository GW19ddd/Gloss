<p align="center">
  <img src="./docs/logo.svg" width="84" alt="Gloss logo" />
</p>

<h1 align="center">Gloss · 旁注</h1>

<p align="center"><b>A light that annotates your papers · a local, self-hosted AI paper-reading companion</b></p>

<p align="center">
  <img src="./docs/cover.svg" width="760" alt="Gloss — a beam of light illuminating a page, like a gloss written in the margins" />
</p>

<p align="center"><sub><i>A beam of light illuminating a page — like a gloss written in the margins.</i></sub></p>

<p align="center"><a href="./README.zh.md"><b>中文文档 →</b></a> · <a href="./CHANGELOG.md"><b>Changelog</b></a></p>

---

Gloss (旁注) is a **self-hosted, locally-run** research-paper reader. A FastAPI backend serves a
React / PDF.js reader UI and drives an LLM to help you skim, study, translate, and ask questions
about a paper.

The model **defaults to your local `claude` CLI**. It also supports the local `codex` CLI, the Anthropic API,
and **any OpenAI-compatible endpoint** (local vLLM, a claude proxy, etc.). It can even **load and run
Claude / Codex skills** directly against the paper you're reading.

Everything runs on your own machine: one process, one port, open a browser and read.

---

## ✨ Features

| Feature | What it does |
|---|---|
| 📖 **PDF reader** | PDF.js with a real selectable text layer; select text to pop up actions (Explain / Translate / add-to-chat / highlight) |
| 🧠 **Summary** | One-click TL;DR + problem / method / results / contributions / limitations |
| 📝 **Notes** | Structured study notes, **copy** or **download `.md`** |
| 🗺️ **Mind Map** | Interactive React Flow map: zoom, expand/collapse, click a node for its summary and connections |
| 💬 **Chat** | Ask like a colleague — **BM25 retrieval (RAG)** over the whole paper, **streaming**, **multiple saved sessions per paper**, deletable, new-session anytime |
| 💡 **Explain** | Select an equation / term / table and get a one-shot explanation; math rendered with **KaTeX** |
| 🌐 **Translate** | **Sentence-level**, **persistently cached**, **reused across page ranges**; translation-only by default with a show-original toggle; **click a sentence to flash-locate it in the PDF**; for arXiv, **translate the exact LaTeX source** so nothing is missed |
| 📐 **arXiv LaTeX** | A **TeX tab** to read the paper's LaTeX source (exact, no extraction loss) — and translate from it |
| 🖍️ **Auto-highlight** | The AI picks key sentences by category and **anchors colored highlights onto the PDF** |
| ✍️ **Highlights** | Your own multi-color highlights + notes, saved on the page |
| 🔗 **References** | Parses the bibliography, enriches via **Crossref / arXiv**, **each entry is clickable** |
| 🔭 **Scholar** | Find related papers via **Semantic Scholar / arXiv** and **import** them in one click |
| 📚 **Library** | Import by **arXiv id / DOI / URL / PDF upload**, managed in one place |
| 🧩 **Skills** | Discover and run **Claude / Codex skills** against the current paper |
| ➕ **Add to chat** | Select content in the PDF or any panel → send it into Chat and get an answer about it |
| 🎨 **Themes & reading modes** | **7 color themes**, plus PDF reading modes — **Normal / Sepia (护眼) / Night (夜间)** |
| 🗣️ **Languages** | **Interface language** (English / 中文, default English), plus the AI's **answer language** and **translation target language** |
| ⚙️ **Quality** | Long operations keep running across tab switches; panels stay mounted so **scroll position and mind-map viewport are preserved**; **Test-connection** button for each provider |

---

## 🚀 Run it (Linux)

```bash
scripts/setup.sh     # first time only: create backend venv + install deps, install & build the frontend
scripts/run.sh       # serve the app on :8010 (built frontend + API — one process, one port)
```

Then open **`http://<host>:8010`**, paste an arXiv id (e.g. `1706.03762`) or upload a PDF, and start reading.

Port / host are overridable via environment variables:

```bash
GLOSS_PORT=6006 GLOSS_HOST=0.0.0.0 scripts/run.sh
```

- `GLOSS_PORT` — service port (default `8010`)
- `GLOSS_HOST` — bind address (default `0.0.0.0`)
- `GLOSS_DATA_DIR` — data directory (default `backend/data`)

The server listens on `0.0.0.0`, so from another machine reach it via your provider's port mapping or an
SSH tunnel (e.g. `ssh -CNg -L <port>:127.0.0.1:<port> -p <ssh-port> user@host`, then open `http://localhost:<port>`).

> For hot-reload development use `scripts/dev.sh` (uvicorn `--reload` on :8010 + Vite dev server on :5173 proxying `/api`).

---

## 🧰 CLI

```bash
./gloss serve                  # start the web app (prints the URL)
./gloss open <pdf|arxiv|doi>   # import + serve + open the browser
./gloss import <src>           # add a local PDF / arXiv / DOI to the library
./gloss ls                     # list the library
./gloss summarize <id|pdf|arxiv>   # print a summary in the terminal
./gloss chat <id>              # interactive terminal chat
./gloss skills                 # list discovered Claude / Codex skills
```

For example: `./gloss open 1706.03762` opens *Attention Is All You Need* and launches the reader.

---

## 🤖 AI providers & advanced settings

Pick a provider in **Settings** (or edit `backend/data/config.json`):

| Provider | Notes | Key? |
|---|---|---|
| `local_claude` | **Default.** Calls the local `claude` CLI via your subscription | ❌ no key |
| `local_codex` | Calls the local `codex` CLI via your ChatGPT subscription | ❌ no key |
| `anthropic` | Anthropic API, or any Anthropic-compatible endpoint | ✅ `base_url` + `api_key` |
| `openai` | Official OpenAI **or any OpenAI-compatible endpoint** | ✅ `base_url` + `api_key` |

The `openai` entry can point at a **local vLLM** or **claude proxy** (e.g. `http://127.0.0.1:8899/v1`) for a fully-offline setup.

**Advanced (per provider):** model (e.g. `sonnet` / `opus`, a full model id, or blank for the CLI's default) and
**reasoning effort** (`local_claude`: `low … max`; `local_codex`: `minimal … high`). **Answer language** and
**translation target language** are also configurable (both default to Simplified Chinese). Keys are masked by the
Settings API and `backend/data/` is gitignored, so secrets never enter version control.

---

## 🏗️ Architecture

```
backend/          FastAPI (one process mounts every /api/*, and serves the built frontend SPA)
  app/providers/  local_claude · local_codex · anthropic · openai · registry (LLM abstraction)
  app/pdf/        PyMuPDF parsing (text blocks + bboxes) + structure heuristics (sections/refs/sentences)
  app/features/   summarize · explain · translate · chat(RAG) · highlight · notes · mindmap · citations
  app/search/     Scholar search / recommend (Semantic Scholar / arXiv)
  app/skills/     discover & run Claude/Codex SKILL.md skills
  app/library/    SQLite store + importers (arXiv/DOI/PDF)
  app/routers/    papers · ai · citations · scholar · annotations · skills · settings
frontend/         React + Vite + pdfjs-dist + KaTeX + React Flow (built to frontend/dist, served by the backend)
cli/ gloss.py     scripts/ setup.sh · run.sh · dev.sh
```

**Data** lives under `backend/data/`: a SQLite DB (papers / highlights / chats / messages / refs / cache)
plus one folder per paper with its `original.pdf` and parsed `parsed.json`.

---

## 💡 Notes

- **Local `claude` / `codex` run standalone** — they sign in with your existing subscription (no API key),
  and each answer is scoped to the current paper only, never mixed with your personal Claude/Codex config.
- **Your data stays local** — papers, highlights, notes, and chats are stored in a local SQLite database plus
  per-paper files under `backend/data/`; nothing leaves your machine except the external lookups below.
- **External lookups degrade gracefully** — References / Scholar go through the machine's HTTP proxy; if a
  source is offline, Gloss falls back to local data instead of erroring the whole page.
- **Generated results are cached** — summary / notes / mind map / translation / highlights are saved after the
  first generation and reused on re-entry, so you don't re-spend compute or quota.

---

## 🙏 Acknowledgments

Gloss is a **local, self-hosted reconstruction of [Moonlight](https://www.themoonlight.io/)** ("an AI colleague
for reading research papers") — rebuilt from scratch to run entirely on your own machine. Its design also draws
inspiration from two lovely projects:

- **[Understand-Anything](https://github.com/Egonex-AI/Understand-Anything)** — for the interactive node-link
  **mind map** (React Flow, click-to-focus, collapsible nodes).
- **[DeepPaperNote](https://github.com/917Dhj/DeepPaperNote)** — for the structured, generated **study notes**.

Huge thanks to the authors of all three. 🙏
