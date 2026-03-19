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
        if not isinstance(text, str):
            text = str(text) if text else ""
        # Strip null bytes — tokenizers reject them
        text = text.replace("\x00", " ")
        for chunk_idx, chunk in enumerate(chunk_text(text)):
            chunk = chunk.strip()
            if not chunk:
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
