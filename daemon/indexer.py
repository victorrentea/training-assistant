"""
Material indexer — watches MATERIALS_FOLDER for PDF/epub/mobi/txt/md/html changes
and keeps the ChromaDB collection up to date.
"""

import hashlib
import json
import sys
import time
import threading
from pathlib import Path

from daemon.rag import _get_collection, _get_embedder, COLLECTION_NAME

SUPPORTED_EXTENSIONS = {".pdf", ".epub", ".mobi", ".txt", ".md", ".html"}
CHUNK_SIZE = 2000        # ~500 tokens at ~4 chars/token
CHUNK_OVERLAP = 200      # ~50 tokens overlap
DEBOUNCE_SECONDS = 2.0
MANIFEST_NAME = ".index-manifest.json"


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
    """Extract text from .mobi using the mobi PyPI package. Best-effort with clear error on failure."""
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

def index_file(path: Path, base_folder: Path) -> bool:
    source_key = str(path.relative_to(base_folder))
    print(f"[indexer] Indexing {source_key}…", flush=True)
    try:
        pages = extract_pages(path)
    except Exception as e:
        print(f"[indexer] Failed to parse {source_key}: {e}", file=sys.stderr)
        return False

    collection = _get_collection()
    embedder = _get_embedder()

    ids, documents, metadatas, embeddings = [], [], [], []
    for page_num, text in pages:
        if not isinstance(text, str):
            text = str(text) if text else ""
        # Remove null bytes and lone surrogates that break tokenizers
        text = text.replace("\x00", " ")
        text = text.encode("utf-8", errors="replace").decode("utf-8")
        for chunk_idx, chunk in enumerate(chunk_text(text)):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                emb = embedder.encode(chunk).tolist()
            except Exception as e:
                print(f"[indexer] Skipping chunk {page_num}::{chunk_idx} of {source_key}: {e}", file=sys.stderr)
                continue
            ids.append(f"{source_key}::{page_num}::{chunk_idx}")
            documents.append(chunk)
            # Classify as slides if the path contains a 'slides' folder segment
            parts = Path(source_key).parts
            source_type = "slides" if any(p.lower() == "slides" for p in parts) else "book"
            metadatas.append({"source": source_key, "page": page_num, "source_type": source_type})
            embeddings.append(emb)

    if not ids:
        print(f"[indexer] No content extracted from {source_key}", file=sys.stderr)
        return False

    collection.upsert(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
    print(f"[indexer] Indexed {len(ids)} chunks from {source_key}", flush=True)
    return True


def deindex_file(source_key: str) -> None:
    try:
        collection = _get_collection()
        collection.delete(where={"source": source_key})
        print(f"[indexer] Removed {source_key} from index", flush=True)
    except Exception as e:
        print(f"[indexer] Failed to deindex {source_key}: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Initial full index
# ---------------------------------------------------------------------------

def _manifest_path(folder: Path) -> Path:
    return folder / MANIFEST_NAME


def _load_manifest(folder: Path) -> dict[str, str]:
    path = _manifest_path(folder)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        files = data.get("files", {})
        return files if isinstance(files, dict) else {}
    except Exception as e:
        print(f"[indexer] Failed to read manifest {path.name}: {e}", file=sys.stderr)
        return {}


def _save_manifest(folder: Path, files: dict[str, str]) -> None:
    path = _manifest_path(folder)
    payload = {"version": 1, "files": dict(sorted(files.items()))}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _iter_supported_files(folder: Path) -> list[Path]:
    return sorted(
        [f for f in folder.rglob("*") if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS],
        key=lambda p: str(p.relative_to(folder)),
    )


def _upsert_file_if_needed(path: Path, folder: Path, manifest_files: dict[str, str]) -> bool:
    source_key = str(path.relative_to(folder))
    new_hash = _hash_file(path)
    old_hash = manifest_files.get(source_key)
    if old_hash == new_hash:
        return False

    if old_hash is not None:
        deindex_file(source_key)

    ok = index_file(path, folder)
    if ok:
        manifest_files[source_key] = new_hash
        return True

    if old_hash is None:
        manifest_files.pop(source_key, None)
    return False


def index_all(folder: Path) -> None:
    files = _iter_supported_files(folder)
    manifest_files = _load_manifest(folder)

    print(f"[indexer] Startup sync of {len(files)} files in {folder} (recursive)…", flush=True)

    current_keys = {str(f.relative_to(folder)) for f in files}
    stale_keys = sorted(set(manifest_files) - current_keys)
    for source_key in stale_keys:
        deindex_file(source_key)
        manifest_files.pop(source_key, None)

    indexed_count = 0
    skipped_count = 0
    for f in files:
        changed = _upsert_file_if_needed(f, folder, manifest_files)
        if changed:
            indexed_count += 1
        else:
            skipped_count += 1

    _save_manifest(folder, manifest_files)
    print(
        "[indexer] Startup sync complete "
        f"(indexed/updated={indexed_count}, unchanged={skipped_count}, removed={len(stale_keys)}).",
        flush=True,
    )


# ---------------------------------------------------------------------------
# Watchdog event handler
# ---------------------------------------------------------------------------

def _make_handler(folder: Path):
    from watchdog.events import FileSystemEventHandler

    class _Handler(FileSystemEventHandler):
        def __init__(self):
            self._pending: dict[str, float] = {}
            self._lock = threading.Lock()
            self._manifest_files = _load_manifest(folder)
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
                        try:
                            source_key = str(p.relative_to(folder))
                        except ValueError:
                            source_key = p.name
                        deindex_file(source_key)
                        self._manifest_files.pop(source_key, None)
                        _save_manifest(folder, self._manifest_files)
                    else:
                        if p.exists():
                            changed = _upsert_file_if_needed(p, folder, self._manifest_files)
                            if changed:
                                _save_manifest(folder, self._manifest_files)

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
        observer.schedule(handler, str(folder), recursive=True)
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
