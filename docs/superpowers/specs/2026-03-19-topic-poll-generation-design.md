# Topic-Based Poll Generation with RAG — Design Spec

**Date:** 2026-03-19
**Status:** Approved

---

## Overview

Add a second poll generation mode to the host panel: **topic-based generation**. The host types a short topic (e.g. "circuit breaker", "outbox table") and the system retrieves relevant content from local PDF training materials via RAG, then asks Claude to craft a debate-triggering poll question grounded in those materials.

The key constraint: heavy ML dependencies (ChromaDB, sentence-transformers) must never reach Railway. They live only in a local `daemon/` sub-project on the trainer's Mac.

---

## Project Structure

```
training-assistant/
├── main.py                  ← FastAPI server (unchanged, deployed to Railway)
├── pyproject.toml           ← Server deps only: fastapi, uvicorn, websockets, anthropic
├── static/                  ← Host + participant UI
├── quiz_generator.py        ← Interactive CLI (root, imports quiz_core)
├── quiz_daemon.py           ← Daemon entry point (root, imports quiz_core)
├── quiz_core.py             ← Shared helpers; search_materials() uses dynamic import
│
└── daemon/                  ← NEW — local Mac only, never deployed
    ├── pyproject.toml       ← Heavy deps: chromadb, sentence-transformers, pypdf, watchdog
    ├── indexer.py           ← PDF watcher + ChromaDB indexing
    ├── rag.py               ← search_materials() implementation
    └── README.md            ← Setup instructions
```

---

## Section 1: Dependency Isolation

**Root `pyproject.toml`** (Railway):
```toml
dependencies = ["fastapi", "uvicorn[standard]", "websockets", "anthropic"]
```

**`daemon/pyproject.toml`** (local Mac only):
```toml
[project]
name = "workshop-daemon"
dependencies = [
    "anthropic",
    "chromadb",
    "sentence-transformers",
    "pypdf",
    "watchdog",
]
```

**Local one-time setup:**
```bash
cd daemon && pip install -e . && cd ..
python3 quiz_daemon.py
```

Railway ignores `daemon/` entirely — it has no Procfile or startup hook pointing at it.

**`.gitignore` additions:** `daemon/__pycache__/`, `daemon/.venv/`

The ChromaDB index lives at `~/.workshop-rag/chroma/` — local only, not in the repo.

---

## Section 2: Indexing Pipeline (`daemon/indexer.py`)

**Trigger:** Background thread started by the daemon using `watchdog`, monitoring `MATERIALS_FOLDER` (configurable via env var, default `~/Documents/workshop-materials/`) for PDF add/modify/delete events.

**Flow:**
1. Extract text page-by-page using `pypdf`
2. Split into ~500-token chunks with 50-token overlap (character-based, no heavy framework)
3. Embed with `sentence-transformers` model `all-mpnet-base-v2` (high quality)
4. Upsert into ChromaDB collection at `~/.workshop-rag/chroma/` — document ID = `filename::page`, so only changed files re-index
5. Log: `[indexer] Indexed 42 chunks from "microservices-patterns.pdf" (p.1-12)`

**First run:** All PDFs indexed (~5–15 min for 150MB). Incremental updates take seconds.

**Materials folder:** Flat — all PDFs directly in the folder.

---

## Section 3: RAG Search (`daemon/rag.py`)

**`search_materials(query: str) -> list[dict]`**

1. Load ChromaDB collection from `~/.workshop-rag/chroma/`
2. Embed query with the same `all-mpnet-base-v2` model
3. Return top-5 most similar chunks as `[{"content": ..., "source": ..., "page": ...}]`
4. If collection empty or missing: return `[{"content": "No materials indexed yet.", "source": "N/A", "page": "N/A"}]`

**Integration in `quiz_core.py`** — replace FAISS stub with dynamic import:

```python
def search_materials(query: str) -> list:
    try:
        from daemon.rag import search_materials as _search
        return _search(query)
    except ImportError:
        return [{"content": "RAG not available (daemon deps not installed).", "source": "N/A", "page": "N/A"}]
```

This keeps `quiz_core.py` importable by Railway (no ChromaDB), while the daemon gets full RAG.

---

## Section 4: Daemon Integration

**New field in `/api/quiz-request` response:**
```json
{"request": {"minutes": 30, "topic": "circuit breaker"}}
```

`topic` is optional. When present, the daemon sets `config.topic` and calls `generate_quiz()` which:
- Sends `TOPIC: circuit breaker` to Claude
- Claude calls `search_materials()` via tool use → retrieves PDF chunks
- Claude crafts question grounded in retrieved materials, fills `source` + `page` fields

No structural changes to `quiz_daemon.py`'s main loop — just pass `topic` into config.

---

## Section 5: Host UI Changes (`static/host.html` / `host.js`)

The existing "Generate" row gains a topic text input to its left:

```
[topic input — placeholder: "topic (optional)"]  [🤖 Generate from transcript]
                                                    ↕ (label changes live)
                                                  [🔍 Generate from topic]
```

**Behavior:**
- Input **empty** → button: `🤖 Generate from transcript` → sends `{minutes: N}` (existing flow)
- Input **has text** → button: `🔍 Generate from topic` → sends `{topic: "..."}` (no minutes)
- Button label updates live on `input` event

The preview card, launch button, and refine flow are identical regardless of generation mode.

---

## Server Changes (`main.py`)

- `/api/quiz-request` POST body gains optional `topic: str | None` field
- `AppState.quiz_request` stores `topic` alongside `minutes`
- GET `/api/quiz-request` returns `topic` in the response for the daemon to read

No other server changes.

---

## Out of Scope

- Web UI for triggering re-indexing (daemon auto-detects file changes)
- Multi-folder materials support
- Web search integration (Claude's general knowledge covers this without additional tooling)
- Subfolder organization of materials
