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
├── main.py                  ← FastAPI server (deployed to Railway)
├── pyproject.toml           ← Server deps only: fastapi, uvicorn, websockets, anthropic
├── static/                  ← Host + participant UI
├── quiz_generator.py        ← Interactive CLI (root, imports quiz_core)
├── quiz_daemon.py           ← Daemon entry point (root, imports quiz_core)
├── quiz_core.py             ← Shared helpers; search_materials() replaced with dynamic import
│
└── daemon/                  ← NEW — local Mac only, never deployed
    ├── __init__.py          ← Empty; makes daemon/ a Python package
    ├── pyproject.toml       ← Heavy deps: chromadb, sentence-transformers, pypdf, watchdog
    ├── indexer.py           ← Material watcher + ChromaDB indexing (PDF, epub, mobi)
    ├── rag.py               ← search_materials() implementation
    └── README.md            ← Setup instructions
```

---

## Section 1: Dependency Isolation

**Root `pyproject.toml`** (Railway — unchanged):
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
    "ebooklib",
    "mobi",
    "watchdog",
]
```

**Local one-time setup:**
```bash
# From repo root — installs chromadb, sentence-transformers, etc. into system Python
pip install -e daemon/
python3 quiz_daemon.py
```

**Import resolution:** `from daemon.rag import search_materials` works because scripts are run from the repo root (`python3 quiz_daemon.py`), which puts the repo root on `sys.path` automatically. The `daemon/__init__.py` makes `daemon/` a package. No `cd daemon/` step needed; `pip install -e daemon/` only installs the heavy deps, not the package path itself.

Railway ignores `daemon/` entirely — it has no Procfile or startup hook pointing at it.

**`.gitignore` additions:** `daemon/__pycache__/`, `daemon/.venv/`

The ChromaDB index lives at `~/.workshop-rag/chroma/` — local only, not in the repo.

---

## Section 2: Indexing Pipeline (`daemon/indexer.py`)

**Trigger:** Background thread started by the daemon using `watchdog`, monitoring `MATERIALS_FOLDER` (configurable via env var, default `~/Documents/workshop-materials/`) for PDF add/modify/delete events.

**ChromaDB collection name:** `"workshop_materials"` — shared constant between `indexer.py` and `rag.py`.

**Flow (add/modify):**
1. Extract text by page/chapter using the appropriate parser: `pypdf` for `.pdf`, `ebooklib` for `.epub`, `mobi` (or kindleunpack) for `.mobi`
2. Split each page into ~500-token chunks with 50-token overlap (character-based splitter, no heavy framework)
3. Embed chunks with `sentence-transformers` model `all-mpnet-base-v2`
4. Upsert into ChromaDB at `~/.workshop-rag/chroma/` — document ID = `"{filename}::{page}::{chunk_idx}"`; also store `source=filename` and `page` as metadata fields
5. Log: `[indexer] Indexed 42 chunks from "microservices-patterns.pdf" (p.1-12)`

**Flow (delete):** Use `collection.delete(where={"source": filename})` — simpler than fetching all IDs and filtering in Python, and works directly with ChromaDB's metadata filter API.

**First run:** All PDFs indexed. With `all-mpnet-base-v2` on CPU, expect 15–30 min for 150MB of PDFs. During this window `rag.py` returns the "No materials indexed yet" fallback — Claude's general knowledge fills the gap and the host is informed via `source: "N/A"` in the result.

**Materials folder:** Flat — all PDFs directly in the folder, no subfolders. `TRANSCRIPTION_FOLDER` must also exist (even if empty) because `config_from_env()` validates it on startup — create an empty directory if you only use topic mode.

**Supported formats:**
- `.pdf` — `pypdf`, page by page
- `.epub` — `ebooklib`, chapter by chapter
- `.mobi` — `mobi` library (or kindleunpack), chapter by chapter
- `.txt`, `.md` — read directly, split into chunks (no external parser)
- `.html` — strip tags with stdlib `html.parser`, then chunk as plain text (no extra dep)

All formats follow the same chunk → embed → upsert pipeline. Add `ebooklib` and `mobi` to `daemon/pyproject.toml` deps. Watchdog watches for all six extensions.

**Watchdog debounce:** Wait 2 seconds after the last modify event before starting indexing, to avoid parsing partially-written files during copy operations.

---

## Section 3: RAG Search (`daemon/rag.py`)

**`search_materials(query: str) -> list[dict]`**

1. Load ChromaDB collection `"workshop_materials"` from `~/.workshop-rag/chroma/`
2. Embed query with the same `all-mpnet-base-v2` model
3. Return top-5 most similar chunks as `[{"content": ..., "source": ..., "page": ...}]`
4. If collection empty or missing: return `[{"content": "No materials indexed yet. Run the daemon first.", "source": "N/A", "page": "N/A"}]`

**Changes to `quiz_core.py`** — replace the existing FAISS/LangChain `search_materials()` stub (lines 266–290) with:

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

### Server model changes (`main.py`)

Update `QuizRequest` Pydantic model with a validator that requires exactly one of the two fields:
```python
class QuizRequest(BaseModel):
    minutes: int | None = None   # None = topic-only mode
    topic: str | None = None

    @model_validator(mode="after")
    def exactly_one_mode(self):
        if bool(self.minutes) == bool(self.topic):
            raise ValueError("Provide either 'minutes' (transcript mode) or 'topic' (topic mode), not both or neither.")
        return self
```

Update the status message for topic mode (currently uses `body.minutes` literally):
```python
if body.topic:
    state.quiz_request = {"minutes": None, "topic": body.topic}
    status_msg = f"Waiting for daemon (topic: {body.topic})…"
else:
    state.quiz_request = {"minutes": body.minutes or 30, "topic": None}
    status_msg = f"Waiting for daemon (last {body.minutes or 30} min)…"
```

GET `/api/quiz-request` returns `state.quiz_request` dict unchanged.

### `quiz_core.py` — new `auto_generate_topic` function

Add alongside `auto_generate`:

```python
def auto_generate_topic(topic: str, config: Config) -> Optional[tuple]:
    """Generate a quiz from a topic using RAG. Returns (quiz, topic_context) or None."""
    post_status("generating", f"Generating question about '{topic}'…", config)
    topic_config = dataclasses.replace(config, topic=topic)
    try:
        quiz = generate_quiz("", topic_config)
    except RuntimeError as e:
        post_status("error", str(e), topic_config)
        return None
    print_quiz(quiz)
    topic_context = f"TOPIC: {topic}"   # used as last_text for refine context
    try:
        _post_json(f"{config.server_url}/api/quiz-preview", {
            "question": quiz["question"],
            "options": quiz["options"],
            "multi": len(quiz.get("correct_indices", [])) > 1,
            "correct_indices": quiz.get("correct_indices", []),
        }, config.host_username, config.host_password)
    except RuntimeError as e:
        post_status("error", f"Failed to post preview: {e}", config)
        return None
    post_status("done", "✅ Question ready — review and fire from host panel.", config)
    return quiz, topic_context
```

Key points:
- Uses `dataclasses.replace(config, topic=topic)` to avoid mutating the shared config object
- Returns `topic_context = "TOPIC: {topic}"` as `last_text` so the refine flow has meaningful context for Claude even without a transcript

### `quiz_daemon.py` — daemon loop changes

Update the import line to include `auto_generate_topic`:
```python
from quiz_core import (
    config_from_env, auto_generate, auto_generate_topic, auto_refine,
    _get_json, DAEMON_POLL_INTERVAL,
)
```

Main loop:
```python
req = data.get("request")
if req:
    topic = req.get("topic")
    minutes = req.get("minutes")
    if topic:
        print(f"\n[daemon] Topic request: '{topic}'")
        result = auto_generate_topic(topic, config)
    else:
        minutes = minutes or config.minutes
        print(f"\n[daemon] Transcript request: last {minutes} min")
        result = auto_generate(minutes, config)
    if result:
        last_quiz, last_text = result
    else:
        last_quiz, last_text = None, None
```

Refine flow is unchanged — `last_text` is either the transcript or `"TOPIC: {topic}"`, both work as context for `refine_quiz`.

---

## Section 5: Host UI Changes (`static/host.html` / `host.js`)

The existing "Generate" row gains a topic text input to its left:

```
[topic input — placeholder: "topic (optional)"]  [🤖 Generate from transcript]
                                                    ↕ (label changes live on input)
                                                  [🔍 Generate from topic]
```

**Behavior:**
- Input **empty** → button label: `🤖 Generate from transcript` → sends `{minutes: N, topic: null}`
- Input **has text** → button label: `🔍 Generate from topic` → sends `{topic: "...", minutes: null}`
- Label updates live on `input` event (no debounce needed)

The preview card, launch button, and refine flow are identical regardless of generation mode. Refine requests operate on the already-generated quiz and pass `last_text` (which is `"TOPIC: {topic}"` in topic mode) — this gives Claude sufficient context for refinement.

---

## Out of Scope

- Web UI for triggering re-indexing (daemon auto-detects file changes via watchdog)
- Multi-folder materials support
- Web search integration (Claude's general knowledge supplements RAG without additional tooling)
- Subfolder organization of materials
- Topic mode retry on Claude API rate-limit (same error handling as transcript mode: post error status, host retries manually)
