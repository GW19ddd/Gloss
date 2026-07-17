# Tests

Black-box tests for Moonlight-Local. They drive the app **only through its public
HTTP API** (`/api/*`) — the same surface the web UI and the `./moonlight` CLI use
— and never import or assert on internal implementation modules. Each test starts
the FastAPI app in-process with `TestClient`, uploads a synthesised PDF, and
checks status codes, response shapes, and end-to-end behaviour.

## Layout

| File | Covers |
| --- | --- |
| `conftest.py` | Harness: data-dir isolation, sample-PDF + `client` fixtures, marker gating |
| `test_health_and_settings.py` | `/api/health`, settings round-trip, API-key masking |
| `test_papers_lifecycle.py` | upload / list / get / patch / delete, 404s, non-PDF rejection |
| `test_pdf_pipeline.py` | pages + bounding boxes, full text, raw PDF bytes, offline reference extraction |
| `test_highlights.py` | manual highlight create / list / patch / delete |
| `test_chats.py` | chat-session create / list, empty message history |
| `test_skills.py` | skill discovery, run guards (unknown id, missing id) |
| `test_validation.py` | 4xx (never 5xx) on malformed requests |
| `test_llm_endpoints.py` | *(gated)* summarize / notes / mind-map / explain / translate / chat / auto-highlight |
| `test_network_endpoints.py` | *(gated)* scholar search, reference resolution |

## Isolation

`MOONLIGHT_DATA_DIR` is pointed at a fresh temp directory **before the app is
imported**, so the SQLite DB, uploaded PDFs and `config.json` all live in a
throwaway location — the real library under `backend/data/` is never touched.

## Running

```bash
# From the repo root, using the backend venv:
backend/.venv/bin/python -m pytest -v

# Deterministic tests only run by default. To also exercise the provider-backed
# and network-backed endpoints:
MOONLIGHT_TEST_LLM=1 backend/.venv/bin/python -m pytest -v          # needs a working LLM provider
MOONLIGHT_TEST_NETWORK=1 backend/.venv/bin/python -m pytest -v      # needs external network
```

Only `pytest` is an extra dependency (`tests/requirements.txt`); everything else
(`fastapi`, `httpx`, `pymupdf`) comes from `backend/requirements.txt`.

## CI

`.github/workflows/ci.yml` runs the deterministic subset on every push/PR (no
provider, no API key, no network) plus a frontend `npm run build`. The gated
`llm` / `network` tests stay skipped in CI.
