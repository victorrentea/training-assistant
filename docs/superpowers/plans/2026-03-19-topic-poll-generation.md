# Topic-Based Poll Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add topic-based poll generation to the host panel — the host types a topic, a local daemon retrieves relevant content from indexed PDF/epub/mobi/txt/md/html materials via RAG (ChromaDB), and Claude crafts a poll question grounded in those materials.

**Architecture:** The `daemon/` subfolder is a new local-only Python sub-project with heavy ML deps (ChromaDB, sentence-transformers) isolated from the Railway-deployed server. A watchdog thread auto-indexes materials; a `search_materials()` dynamic-import shim in `quiz_core.py` delegates to `daemon/rag.py` when available, gracefully degrading otherwise. The server's `/api/quiz-request` gains an optional `topic` field; the daemon reads it and dispatches to a new `auto_generate_topic()` code path.

**Tech Stack:** Python 3.12, FastAPI, ChromaDB, sentence-transformers (`all-mpnet-base-v2`), pypdf, ebooklib, mobi, watchdog, vanilla JS

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `daemon/__init__.py` | Create | Empty — makes `daemon/` a package importable from repo root |
| `daemon/pyproject.toml` | Create | Heavy ML deps declaration (never deployed) |
| `daemon/rag.py` | Create | `search_materials()` using ChromaDB |
| `daemon/indexer.py` | Create | File watcher + multi-format text extraction + ChromaDB upsert |
| `daemon/README.md` | Create | One-time setup instructions |
| `quiz_core.py` | Modify | Replace FAISS stub with dynamic-import shim; add `auto_generate_topic()` |
| `quiz_daemon.py` | Modify | Import `auto_generate_topic`; dispatch topic vs transcript in loop |
| `routers/quiz.py` | Modify | `QuizRequest` model: add `topic` field + validator; fix status message |
| `static/host.html` | Modify | Add topic input field next to Generate button |
| `static/host.js` | Modify | `requestQuiz()`: read topic input, switch button label, send correct payload |
| `.gitignore` | Modify | Add `daemon/__pycache__/`, `daemon/.venv/` |
| `test_main.py` | Modify | Add tests for topic quiz-request endpoint |

---

## Task 1: Create `daemon/` package scaffold

**Files:**
- Create: `daemon/__init__.py`
- Create: `daemon/pyproject.toml`
- Create: `daemon/README.md`
- Modify: `.gitignore`

- [ ] **Step 1: Create `daemon/__init__.py`**

```python
# daemon/__init__.py
```
(Empty file — makes daemon/ a Python package importable from repo root)

- [ ] **Step 2: Create `daemon/pyproject.toml`**

```toml
[project]
name = "workshop-daemon"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "anthropic>=0.85.0",
    "chromadb>=0.5.0",
    "sentence-transformers>=3.0.0",
    "pypdf>=4.0.0",
    "ebooklib>=0.18",
    "mobi>=0.3.3",
    "watchdog>=4.0.0",
]
```

- [ ] **Step 3: Create `daemon/README.md`**

```markdown
# Workshop Daemon — Local Setup

Heavy ML dependencies run locally on the trainer's Mac. Never deployed to Railway.

## One-time setup

From the repo root:
```bash
pip install -e daemon/
```

This installs chromadb, sentence-transformers, and other heavy deps into system Python.

## Running

From the repo root:
```bash
python3 quiz_daemon.py
```

The daemon starts a background indexer thread watching `MATERIALS_FOLDER` for changes,
and polls the server every second for quiz generation requests from the host panel.

## Configuration (in secrets.env)

```
MATERIALS_FOLDER=/Users/yourname/Documents/workshop-materials
TRANSCRIPTION_FOLDER=/Users/yourname/Documents/transcriptions  # must exist, can be empty
ANTHROPIC_API_KEY=sk-ant-...
WORKSHOP_SERVER_URL=https://interact.victorrentea.ro
HOST_USERNAME=host
HOST_PASSWORD=...
```

## First indexing

On first run, all materials are indexed. With `all-mpnet-base-v2` on CPU, expect 15–30 min
for 150MB of PDFs. During this window, topic-mode generation falls back to Claude's general
knowledge. Subsequent runs only re-index changed files (seconds).

## Supported formats

`.pdf`, `.epub`, `.mobi`, `.txt`, `.md`, `.html`

## ChromaDB index location

`~/.workshop-rag/chroma/` — local only, not in git.
```

- [ ] **Step 4: Add daemon dirs to `.gitignore`**

Open `.gitignore` and append:
```
daemon/__pycache__/
daemon/.venv/
```

- [ ] **Step 5: Commit**

```bash
git add daemon/__init__.py daemon/pyproject.toml daemon/README.md .gitignore
git commit -m "chore: scaffold daemon/ sub-project with deps and README"
```

---

## Task 2: Implement `daemon/rag.py` — RAG search

**Files:**
- Create: `daemon/rag.py`

- [ ] **Step 1: Create `daemon/rag.py`**

```python
"""
RAG search over workshop materials using ChromaDB.

Exposes search_materials(query) — called by quiz_core.py via dynamic import.
"""

from pathlib import Path

CHROMA_PATH = Path.home() / ".workshop-rag" / "chroma"
COLLECTION_NAME = "workshop_materials"
EMBED_MODEL = "all-mpnet-base-v2"
TOP_K = 5

_embedder = None
_collection = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer(EMBED_MODEL)
    return _embedder


def _get_collection():
    global _collection
    if _collection is None:
        import chromadb
        client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        _collection = client.get_or_create_collection(COLLECTION_NAME)
    return _collection


def search_materials(query: str) -> list[dict]:
    """Return top-K chunks matching query. Gracefully returns fallback if index is empty."""
    try:
        collection = _get_collection()
        if collection.count() == 0:
            return [{"content": "No materials indexed yet. Run the daemon first.", "source": "N/A", "page": "N/A"}]
        embedder = _get_embedder()
        query_embedding = embedder.encode(query).tolist()
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(TOP_K, collection.count()),
            include=["documents", "metadatas"],
        )
        chunks = []
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            chunks.append({
                "content": doc,
                "source": meta.get("source", "Unknown"),
                "page": str(meta.get("page", "N/A")),
            })
        return chunks
    except Exception as e:
        return [{"content": f"RAG search failed: {e}", "source": "Error", "page": "N/A"}]
```

- [ ] **Step 2: Verify it imports cleanly (no runtime error at import time)**

```bash
python3 -c "from daemon.rag import search_materials; print('OK')"
```
Expected: `OK` (no ImportError — chromadb/sentence-transformers lazy-loaded)

- [ ] **Step 3: Commit**

```bash
git add daemon/rag.py
git commit -m "feat: add daemon/rag.py — ChromaDB RAG search for workshop materials"
```

---

## Task 3: Implement `daemon/indexer.py` — file watcher + multi-format indexer

**Files:**
- Create: `daemon/indexer.py`

- [ ] **Step 1: Create `daemon/indexer.py`**

```python
"""
Material indexer — watches MATERIALS_FOLDER for PDF/epub/mobi/txt/md/html changes
and keeps the ChromaDB collection up to date.
"""

import sys
import time
import threading
from pathlib import Path

from daemon.rag import _get_collection, _get_embedder, COLLECTION_NAME

SUPPORTED_EXTENSIONS = {".pdf", ".epub", ".mobi", ".txt", ".md", ".html"}
CHUNK_SIZE = 2000        # ~500 tokens at ~4 chars/token
CHUNK_OVERLAP = 200      # ~50 tokens overlap
DEBOUNCE_SECONDS = 2.0


# ---------------------------------------------------------------------------
# Text extraction (one function per format)
# ---------------------------------------------------------------------------

def _extract_pdf(path: Path) -> list[tuple[int, str]]:
    """Returns list of (page_number, text) tuples."""
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            pages.append((i + 1, text))
    return pages


def _extract_epub(path: Path) -> list[tuple[int, str]]:
    import ebooklib
    from ebooklib import epub
    from html.parser import HTMLParser

    class _TextExtractor(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []
        def handle_data(self, data):
            self.parts.append(data)
        def get_text(self):
            return " ".join(self.parts)

    book = epub.read_epub(str(path))
    chapters = []
    for i, item in enumerate(book.get_items_of_type(ebooklib.ITEM_DOCUMENT)):
        parser = _TextExtractor()
        parser.feed(item.get_content().decode("utf-8", errors="replace"))
        text = parser.get_text().strip()
        if text:
            chapters.append((i + 1, text))
    return chapters


def _extract_mobi(path: Path) -> list[tuple[int, str]]:
    """Extract text from .mobi using the mobi PyPI package.

    The `mobi` package (pip install mobi) exposes mobi.Mobi; call .read() then
    access .htmlFile for the raw HTML content, or fall back to reading the
    extracted temp file. If the API is unavailable at runtime, log a warning
    and return empty.

    NOTE: Verify the installed mobi package API before using. If `mobi.Mobi`
    is not available, an alternative is to use `kindleunpack` (install via
    `pip install kindleunpack`) and call `kindleunpack.unpackBook(str(path), tempdir)`.
    For now, implement a best-effort approach with a clear error message:
    """
    from html.parser import HTMLParser
    try:
        import mobi as mobi_lib
        book = mobi_lib.Mobi(str(path))
        book.parse()
        html_content = book.htmlFile or b""
        if isinstance(html_content, bytes):
            html_content = html_content.decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[indexer] mobi extraction failed for {path.name}: {e} — skipping", file=sys.stderr)
        print(f"[indexer] Hint: ensure 'mobi' package is installed: pip install mobi", file=sys.stderr)
        return []

    class _TextExtractor(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []
        def handle_data(self, data):
            self.parts.append(data)
        def get_text(self):
            return " ".join(self.parts)

    parser = _TextExtractor()
    parser.feed(html_content)
    text = parser.get_text().strip()
    return [(1, text)] if text else []


def _extract_html(path: Path) -> list[tuple[int, str]]:
    from html.parser import HTMLParser

    class _TextExtractor(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []
        def handle_data(self, data):
            self.parts.append(data)
        def get_text(self):
            return " ".join(self.parts)

    html = path.read_text(encoding="utf-8", errors="replace")
    parser = _TextExtractor()
    parser.feed(html)
    return [(1, parser.get_text().strip())]


def _extract_text(path: Path) -> list[tuple[int, str]]:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    return [(1, text)] if text else []


def extract_pages(path: Path) -> list[tuple[int, str]]:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return _extract_pdf(path)
    elif ext == ".epub":
        return _extract_epub(path)
    elif ext == ".mobi":
        return _extract_mobi(path)
    elif ext == ".html":
        return _extract_html(path)
    else:  # .txt, .md
        return _extract_text(path)


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping character-based chunks."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


# ---------------------------------------------------------------------------
# Index / deindex
# ---------------------------------------------------------------------------

def index_file(path: Path) -> None:
    filename = path.name
    print(f"[indexer] Indexing {filename}…", flush=True)
    try:
        pages = extract_pages(path)
    except Exception as e:
        print(f"[indexer] Failed to parse {filename}: {e}", file=sys.stderr)
        return

    collection = _get_collection()
    embedder = _get_embedder()

    ids, documents, metadatas = [], [], []
    for page_num, text in pages:
        for chunk_idx, chunk in enumerate(chunk_text(text)):
            if not chunk.strip():
                continue
            ids.append(f"{filename}::{page_num}::{chunk_idx}")
            documents.append(chunk)
            metadatas.append({"source": filename, "page": page_num})

    if not ids:
        print(f"[indexer] No content extracted from {filename}", file=sys.stderr)
        return

    embeddings = embedder.encode(documents).tolist()
    collection.upsert(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
    print(f"[indexer] Indexed {len(ids)} chunks from {filename}", flush=True)


def deindex_file(filename: str) -> None:
    try:
        collection = _get_collection()
        collection.delete(where={"source": filename})
        print(f"[indexer] Removed {filename} from index", flush=True)
    except Exception as e:
        print(f"[indexer] Failed to deindex {filename}: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Initial full index
# ---------------------------------------------------------------------------

def index_all(folder: Path) -> None:
    files = [f for f in folder.iterdir() if f.suffix.lower() in SUPPORTED_EXTENSIONS]
    print(f"[indexer] Initial indexing of {len(files)} files in {folder}…", flush=True)
    for f in files:
        index_file(f)
    print("[indexer] Initial indexing complete.", flush=True)


# ---------------------------------------------------------------------------
# Watchdog event handler
# ---------------------------------------------------------------------------

def _make_handler(folder: Path):
    from watchdog.events import FileSystemEventHandler

    class _Handler(FileSystemEventHandler):
        def __init__(self):
            self._pending: dict[str, float] = {}
            self._lock = threading.Lock()
            # Start debounce worker
            t = threading.Thread(target=self._debounce_worker, daemon=True)
            t.start()

        def _schedule(self, path: str, action: str) -> None:
            with self._lock:
                self._pending[path] = (time.monotonic(), action)

        def _debounce_worker(self) -> None:
            while True:
                time.sleep(0.5)
                now = time.monotonic()
                with self._lock:
                    due = {p: (ts, act) for p, (ts, act) in self._pending.items()
                           if now - ts >= DEBOUNCE_SECONDS}
                    for p in due:
                        del self._pending[p]
                for path, (_, action) in due.items():
                    p = Path(path)
                    if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
                        continue
                    if action == "delete":
                        deindex_file(p.name)
                    else:
                        if p.exists():
                            index_file(p)

        def on_created(self, event):
            if not event.is_directory:
                self._schedule(event.src_path, "upsert")

        def on_modified(self, event):
            if not event.is_directory:
                self._schedule(event.src_path, "upsert")

        def on_deleted(self, event):
            if not event.is_directory:
                self._schedule(event.src_path, "delete")

        def on_moved(self, event):
            if not event.is_directory:
                self._schedule(event.src_path, "delete")
                self._schedule(event.dest_path, "upsert")

    return _Handler()


# ---------------------------------------------------------------------------
# Public API: start background indexer thread
# ---------------------------------------------------------------------------

def start_indexer(folder: Path) -> None:
    """Start background thread: initial full index + watchdog for changes."""
    def _run():
        index_all(folder)
        from watchdog.observers import Observer
        handler = _make_handler(folder)
        observer = Observer()
        observer.schedule(handler, str(folder), recursive=False)
        observer.start()
        print(f"[indexer] Watching {folder} for changes…", flush=True)
        try:
            while True:
                time.sleep(1)
        except Exception:
            observer.stop()
        observer.join()

    t = threading.Thread(target=_run, daemon=True, name="indexer")
    t.start()
```

- [ ] **Step 2: Smoke-test the chunker in isolation**

```bash
python3 -c "
from daemon.indexer import chunk_text
chunks = chunk_text('x' * 5000)
assert len(chunks) == 3, f'expected 3 chunks, got {len(chunks)}'
assert all(len(c) <= 2000 for c in chunks)
print('chunker OK')
"
```
Expected: `chunker OK`

- [ ] **Step 3: Commit**

```bash
git add daemon/indexer.py
git commit -m "feat: add daemon/indexer.py — multi-format material indexer with watchdog"
```

---

## Task 4: Replace FAISS stub in `quiz_core.py` with dynamic-import shim

**Files:**
- Modify: `quiz_core.py` (lines 266–290)

- [ ] **Step 1: Replace `search_materials` in `quiz_core.py`**

Find the block from line 266 to 290 (the FAISS/LangChain stub) and replace it with:

```python
def search_materials(query: str) -> list:
    """Delegate to daemon/rag.py if available; graceful fallback otherwise."""
    try:
        from daemon.rag import search_materials as _search
        return _search(query)
    except ImportError:
        return [{"content": "RAG not available (run: pip install -e daemon/).", "source": "N/A", "page": "N/A"}]
```

- [ ] **Step 2: Verify Railway import still works (no heavy deps at import time)**

```bash
python3 -c "from quiz_core import generate_quiz, search_materials; print('OK')"
```
Expected: `OK` — no ImportError, no chromadb import attempted

- [ ] **Step 3: Write test for graceful fallback**

Add to `test_main.py` (or a new `test_quiz_core.py`):

```python
def test_search_materials_fallback_without_daemon(monkeypatch):
    """search_materials returns a safe fallback when daemon deps are not installed."""
    import sys, quiz_core
    # Remove daemon.rag from sys.modules so the dynamic import triggers ImportError
    monkeypatch.setitem(sys.modules, "daemon.rag", None)
    results = quiz_core.search_materials("circuit breaker")
    assert len(results) == 1
    assert results[0]["source"] == "N/A"
```

- [ ] **Step 4: Run the test**

```bash
pytest test_main.py::test_search_materials_fallback_without_daemon -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quiz_core.py test_main.py
git commit -m "feat: replace FAISS stub with dynamic-import shim in quiz_core.search_materials"
```

---

## Task 5: Add `auto_generate_topic()` to `quiz_core.py`

**Files:**
- Modify: `quiz_core.py`

- [ ] **Step 1: Fix import at top of `quiz_core.py`**

The file currently has `from dataclasses import dataclass`. Change it to also import `replace`:
```python
from dataclasses import dataclass, replace
```

Then in `auto_generate_topic`, use `replace(config, topic=topic)` (not `dataclasses.replace`).

- [ ] **Step 2: Add `auto_generate_topic` alongside `auto_generate`**

After the `auto_generate` function, add:

```python
def auto_generate_topic(topic: str, config: Config) -> Optional[tuple]:
    """Generate a quiz from a topic using RAG. Returns (quiz, topic_context) or None."""
    post_status("generating", f"Generating question about '{topic}'…", config)
    topic_config = replace(config, topic=topic)
    try:
        quiz = generate_quiz("", topic_config)
    except RuntimeError as e:
        post_status("error", str(e), topic_config)
        return None
    print_quiz(quiz)
    topic_context = f"TOPIC: {topic}"
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

- [ ] **Step 3: Verify import**

```bash
python3 -c "from quiz_core import auto_generate_topic; print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add quiz_core.py
git commit -m "feat: add auto_generate_topic() to quiz_core for topic-based generation"
```

---

## Task 6: Update `quiz_daemon.py` to dispatch topic vs transcript

**Files:**
- Modify: `quiz_daemon.py`

- [ ] **Step 1: Update import line in `quiz_daemon.py`**

Find:
```python
from quiz_core import (
    config_from_env, auto_generate, auto_refine,
    _get_json, DAEMON_POLL_INTERVAL,
)
```
Replace with:
```python
from quiz_core import (
    config_from_env, auto_generate, auto_generate_topic, auto_refine,
    _get_json, DAEMON_POLL_INTERVAL,
)
```

- [ ] **Step 2: Update the request dispatch in the daemon loop**

Find the block starting with `req = data.get("request")` and replace it:

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

- [ ] **Step 3: Add indexer startup to `quiz_daemon.py`**

At the top of `run()`, after `config = config_from_env()`, add:

```python
# Start background material indexer
materials_folder_str = os.environ.get("MATERIALS_FOLDER",
    str(Path.home() / "Documents" / "workshop-materials"))
materials_folder = Path(materials_folder_str).expanduser()
if materials_folder.exists():
    from daemon.indexer import start_indexer
    start_indexer(materials_folder)
else:
    print(f"[daemon] MATERIALS_FOLDER not found: {materials_folder} — indexer disabled", file=sys.stderr)
```

- [ ] **Step 4: Ensure `TRANSCRIPTION_FOLDER` exists**

`config_from_env()` in `quiz_core.py` calls `sys.exit(1)` if `TRANSCRIPTION_FOLDER` doesn't exist — even in topic-only mode. The folder must exist (can be empty):
```bash
mkdir -p ~/Documents/transcriptions
```
Document this in `secrets.env` if not already there.

- [ ] **Step 5: Verify syntax**

```bash
python3 -c "import quiz_daemon; print('OK')"
```
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add quiz_daemon.py
git commit -m "feat: dispatch topic vs transcript in daemon loop; start material indexer on startup"
```

---

## Task 7: Update server `QuizRequest` model in `routers/quiz.py`

**Files:**
- Modify: `routers/quiz.py`

- [ ] **Step 1: Update imports at top of `routers/quiz.py`**

Add `model_validator` to pydantic imports:
```python
from pydantic import BaseModel, model_validator
```

- [ ] **Step 2: Replace `QuizRequest` model**

Find:
```python
class QuizRequest(BaseModel):
    minutes: int = 30
```
Replace with:
```python
class QuizRequest(BaseModel):
    minutes: int | None = None   # transcript mode
    topic: str | None = None     # topic mode

    @model_validator(mode="after")
    def exactly_one_mode(self):
        has_minutes = self.minutes is not None and self.minutes > 0
        has_topic = bool(self.topic and self.topic.strip())
        if has_minutes == has_topic:
            raise ValueError("Provide either 'minutes' (transcript mode) or 'topic' (topic mode), not both or neither.")
        return self
```

- [ ] **Step 3: Update `request_quiz` endpoint**

Find:
```python
@router.post("/api/quiz-request")
async def request_quiz(body: QuizRequest):
    state.quiz_request = {"minutes": body.minutes}
    state.quiz_status = {"status": "requested", "message": f"Waiting for daemon (last {body.minutes} min)…"}
    await broadcast({"type": "quiz_status", **state.quiz_status})
    return {"ok": True}
```
Replace with:
```python
@router.post("/api/quiz-request")
async def request_quiz(body: QuizRequest):
    if body.topic:
        state.quiz_request = {"minutes": None, "topic": body.topic}
        msg = f"Waiting for daemon (topic: {body.topic})…"
    else:
        minutes = body.minutes or 30
        state.quiz_request = {"minutes": minutes, "topic": None}
        msg = f"Waiting for daemon (last {minutes} min)…"
    state.quiz_status = {"status": "requested", "message": msg}
    await broadcast({"type": "quiz_status", **state.quiz_status})
    return {"ok": True}
```

- [ ] **Step 4: Write tests**

Add to `test_main.py`:

```python
def test_quiz_request_transcript_mode():
    state.reset()
    client = TestClient(app)
    resp = client.post("/api/quiz-request",
        json={"minutes": 30},
        headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 200
    data = client.get("/api/quiz-request", headers=_HOST_AUTH_HEADERS).json()
    assert data["request"]["minutes"] == 30
    assert data["request"]["topic"] is None


def test_quiz_request_topic_mode():
    state.reset()
    client = TestClient(app)
    resp = client.post("/api/quiz-request",
        json={"topic": "circuit breaker"},
        headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 200
    data = client.get("/api/quiz-request", headers=_HOST_AUTH_HEADERS).json()
    assert data["request"]["topic"] == "circuit breaker"
    assert data["request"]["minutes"] is None


def test_quiz_request_rejects_both_fields():
    client = TestClient(app)
    resp = client.post("/api/quiz-request",
        json={"minutes": 30, "topic": "circuit breaker"},
        headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 422


def test_quiz_request_rejects_neither_field():
    client = TestClient(app)
    resp = client.post("/api/quiz-request",
        json={},
        headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 422
```

Note: `test_main.py` uses `TestClient(app)` directly (no `client` fixture). Follow the same pattern — use `TestClient(app)` inline in each test and call `state.reset()` to clear state between tests. Example:
```python
def test_quiz_request_transcript_mode():
    state.reset()
    client = TestClient(app)
    resp = client.post("/api/quiz-request", ...)
```

- [ ] **Step 5: Run the tests**

```bash
pytest test_main.py::test_quiz_request_transcript_mode test_main.py::test_quiz_request_topic_mode test_main.py::test_quiz_request_rejects_both_fields test_main.py::test_quiz_request_rejects_neither_field -v
```
Expected: all 4 PASS

- [ ] **Step 6: Commit**

```bash
git add routers/quiz.py test_main.py
git commit -m "feat: extend QuizRequest with topic field + validator; update request_quiz endpoint"
```

---

## Task 8: Update host UI — topic input + dynamic button label

**Files:**
- Modify: `static/host.html`
- Modify: `static/host.js`

- [ ] **Step 1: Add topic input to `static/host.html`**

Find the existing `quiz-gen-row` div:
```html
      <div class="quiz-gen-row">
        <div class="quiz-gen-controls">
          <button class="btn btn-warn" id="gen-quiz-btn" onclick="requestQuiz()">🤖 Generate</button>
          <div style="display:flex;align-items:center;gap:.4rem;font-size:.9rem;color:var(--text);">
            from last
            <select id="quiz-minutes" ...>
```

Replace the `quiz-gen-controls` inner div with:
```html
        <div class="quiz-gen-controls">
          <input id="quiz-topic" type="text" maxlength="60" autocomplete="off"
                 placeholder="topic (optional)"
                 oninput="updateGenBtn()"
                 style="background:var(--surface2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:.3rem .6rem;font-size:.9rem;width:10rem;" />
          <button class="btn btn-warn" id="gen-quiz-btn" onclick="requestQuiz()">🤖 Generate from transcript</button>
          <div id="quiz-minutes-row" style="display:flex;align-items:center;gap:.4rem;font-size:.9rem;color:var(--text);">
            from last
            <select id="quiz-minutes" style="background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:.3rem .5rem;font-size:.9rem;cursor:pointer;">
              <option value="15">15 min</option>
              <option value="30" selected>30 min</option>
              <option value="60">1 hour</option>
              <option value="90">1.5 hours</option>
              <option value="480">whole day</option>
            </select>
          </div>
        </div>
```

- [ ] **Step 2: Update `requestQuiz()` in `static/host.js`**

Find:
```javascript
  async function requestQuiz() {
    const minutes = parseInt(document.getElementById('quiz-minutes').value, 10);
    const btn = document.getElementById('gen-quiz-btn');
    btn.disabled = true;
    renderQuizStatus('requested', `Waiting… (${minutes}m)`);
    try {
      await fetch('/api/quiz-request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ minutes }),
      });
    } catch (e) {
      renderQuizStatus('error', 'Failed to reach server.');
    }
    setTimeout(() => { btn.disabled = false; }, 5000);
  }
```
Replace with:
```javascript
  function updateGenBtn() {
    const topic = document.getElementById('quiz-topic').value.trim();
    const btn = document.getElementById('gen-quiz-btn');
    const minutesRow = document.getElementById('quiz-minutes-row');
    if (topic) {
      btn.textContent = '🔍 Generate from topic';
      minutesRow.style.display = 'none';
    } else {
      btn.textContent = '🤖 Generate from transcript';
      minutesRow.style.display = 'flex';
    }
  }

  async function requestQuiz() {
    const topic = document.getElementById('quiz-topic').value.trim();
    const btn = document.getElementById('gen-quiz-btn');
    btn.disabled = true;
    let body, statusMsg;
    if (topic) {
      body = { topic };
      statusMsg = `Waiting… (topic: ${topic})`;
    } else {
      const minutes = parseInt(document.getElementById('quiz-minutes').value, 10);
      body = { minutes };
      statusMsg = `Waiting… (${minutes}m)`;
    }
    renderQuizStatus('requested', statusMsg);
    try {
      await fetch('/api/quiz-request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
    } catch (e) {
      renderQuizStatus('error', 'Failed to reach server.');
    }
    setTimeout(() => { btn.disabled = false; }, 5000);
  }
```

- [ ] **Step 3: Manual smoke test**

Start the server: `python3 -m uvicorn main:app --reload --port 8000`

Open http://localhost:8000/host in a browser.

Verify:
- Topic input appears to the left of the Generate button
- Empty topic → button shows `🤖 Generate from transcript`, minutes dropdown visible
- Type "circuit breaker" → button changes to `🔍 Generate from topic`, minutes dropdown hides
- Clear the topic → button reverts to transcript label, minutes reappears

- [ ] **Step 4: Commit**

```bash
git add static/host.html static/host.js
git commit -m "feat: add topic input to host UI; dynamic Generate button label"
```

---

## Task 9: Final integration smoke test + push

- [ ] **Step 1: Run all tests**

```bash
pytest test_main.py -v
```
Expected: all tests PASS (including the 4 new quiz-request tests)

- [ ] **Step 2: Verify server imports cleanly (no ML deps)**

```bash
python3 -c "from main import app; print('server OK')"
```
Expected: `server OK` — no chromadb or sentence-transformers imported

- [ ] **Step 3: Verify daemon imports cleanly**

```bash
python3 -c "from quiz_daemon import run; print('daemon OK')"
```
Expected: `daemon OK`

- [ ] **Step 4: Push to Railway**

```bash
git push
bash wait-for-deploy.sh &
```

Expected: Railway deploys in ~40-50s. The new topic input appears in the host panel at https://interact.victorrentea.ro/host.
