# Server-Side PDF Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move PDF downloading/caching from daemon to FastAPI backend; daemon becomes a thin file watcher that sends catalog + invalidation events.

**Architecture:** Backend downloads PDFs from Google Drive on demand, caches them in `/tmp/slides-cache/`, deduplicates concurrent requests with per-slug locks, and polls GDrive fingerprints on invalidation. Status is WS-pushed to host UI.

**Tech Stack:** Python/FastAPI (asyncio), vanilla JS, WebSocket

**Spec:** `docs/superpowers/specs/2026-03-28-server-side-pdf-cache-design.md`

---

### Task 1: Clean up PoC code from main.py

**Files:**
- Modify: `main.py` (lines 6-8 imports, lines 59-133 PoC functions, lines 136-143 lifespan)

- [ ] **Step 1: Remove PoC imports and functions**

Remove `ssl`, `urllib.request` imports added in PoC. Remove `_bg_logger`, `_PROBE_DRIVE_URL`, `_DOWNLOAD_DIR`, `_ssl_ctx()`, `_download_pdf_sync()`, `_drive_download_once()`, `_daemon_ping_loop()`. Restore lifespan to just `_stamp_version_js()` + `yield`.

```python
# main.py lifespan should become:
@asynccontextmanager
async def lifespan(app_: FastAPI):
    _stamp_version_js()
    yield
```

Remove the `asyncio`, `ssl`, `urllib.request` imports (keep `asyncio` — it will be needed by Task 3). Remove `timezone` from datetime import.

- [ ] **Step 2: Verify server starts**

Run: `cd /Users/victorrentea/conductor/workspaces/training-assistant/beirut && python3 -m uvicorn main:app --host 127.0.0.1 --port 9999 &` — wait 3s, `curl -s http://127.0.0.1:9999/api/status | python3 -m json.tool`, then `kill %1`.
Expected: JSON response with `backend_version`.

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "chore: remove PoC ping/download code from main.py"
```

---

### Task 2: Add slides cache state fields to AppState

**Files:**
- Modify: `core/state.py` (~line 48-56 slides section, ~line 31 reset method)

- [ ] **Step 1: Read `core/state.py`** to find exact line numbers for slides fields and the `reset()` method.

- [ ] **Step 2: Add new state fields**

Add these fields in the slides section of `__init__` (after existing slides fields):

```python
# Slides cache (server-side GDrive download)
self.slides_catalog: dict[str, dict] = {}           # slug -> {slug, title, drive_export_url}
self.slides_cache_status: dict[str, dict] = {}      # slug -> {status, size_bytes, downloaded_at, title}
self.slides_download_events: dict[str, asyncio.Event] = {}  # slug -> event for waiters
self.slides_gdrive_locks: dict[str, asyncio.Lock] = {}      # slug -> per-slug GDrive lock
self.slides_fingerprints: dict[str, str] = {}        # slug -> last known fingerprint
self.slides_download_semaphore: asyncio.Semaphore = asyncio.Semaphore(3)  # max 3 concurrent cross-slug downloads
```

Add `import asyncio` at top of `core/state.py` if not already present.

- [ ] **Step 3: Remove `slides_uploads` and `slides_meta` fields** — remove `self.slides_uploads: dict[str, dict] = {}` (~line 56) and `self.slides_meta: dict[str, str] = {}` (~line 54). Both are replaced by the new cache fields.

- [ ] **Step 4: Update `reset()` method** — clear the new dicts but preserve `slides_catalog` (daemon may not re-send on soft reset). Clear `slides_cache_status`, `slides_download_events`, `slides_gdrive_locks`, `slides_fingerprints`. Re-create `slides_download_semaphore`.

- [ ] **Step 5: Verify server starts** (same curl check as Task 1 Step 2).

- [ ] **Step 6: Commit**

```bash
git add core/state.py
git commit -m "feat(state): add slides cache fields, remove slides_uploads"
```

---

### Task 3: Create `features/slides/cache.py` — core cache logic

This is the heart of the feature. It handles GDrive download, fingerprint probing, polling, per-slug locking, and daemon log push.

**Files:**
- Create: `features/slides/cache.py`
- Test: `tests/features/slides/test_cache.py`

- [ ] **Step 1: Write unit tests for the cache module**

Create `tests/features/slides/test_cache.py` with these tests (using unittest.mock to patch `urllib.request`):

```python
"""Unit tests for features/slides/cache.py"""
import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path

# Tests to write:

# test_probe_fingerprint_uses_head_first
#   Mock urllib.request.urlopen to return headers with ETag.
#   Call _probe_fingerprint(url). Assert HEAD was used, returns "hdr:..." string.

# test_probe_fingerprint_falls_back_to_get_on_405
#   Mock HEAD to raise HTTPError(405). Mock GET to return PDF bytes.
#   Call _probe_fingerprint(url). Assert GET was used, returns "body:<sha256>" string.

# test_download_pdf_saves_to_cache_dir
#   Mock urlopen to return PDF bytes (b"%PDF-1.4 test content").
#   Call download_slide("test-slug", "https://example.com/export/pdf").
#   Assert file exists at CACHE_DIR / "test-slug.pdf" with correct content.

# test_download_pdf_rejects_non_pdf
#   Mock urlopen to return HTML bytes.
#   Call download_slide(). Assert raises RuntimeError("not a PDF").

# test_concurrent_requests_dedup
#   Start 5 concurrent download_or_wait_cached("slug") calls.
#   Assert urllib.request.urlopen is called exactly once (not 5 times).
#   Assert all 5 calls return the same path.

# test_invalidation_triggers_poll_loop
#   Pre-cache a PDF. Set a known fingerprint.
#   Mock HEAD to return a DIFFERENT fingerprint on 3rd call.
#   Call handle_slide_invalidated("slug").
#   Assert status transitions: cached -> stale -> polling_drive -> downloading -> cached.

# test_invalidation_ignored_if_already_polling
#   Set status to "polling_drive" for a slug.
#   Call handle_slide_invalidated("slug").
#   Assert no new poll task is started.

# test_poll_timeout_after_60s
#   Mock HEAD to always return the SAME fingerprint.
#   Call handle_slide_invalidated with a short timeout (e.g., 1s for test speed).
#   Assert status transitions to "poll_timeout".
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/features/slides/test_cache.py -v`
Expected: ImportError or collection errors (module doesn't exist yet).

- [ ] **Step 3: Implement `features/slides/cache.py`**

```python
"""
Server-side PDF cache — downloads from Google Drive, fingerprint polling, dedup.

Key invariant: at most ONE in-flight HTTP request to GDrive per slug at any time.
All GDrive calls go through the per-slug asyncio.Lock.
"""

import asyncio
import hashlib
import logging
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from core.state import state
from core.messaging import broadcast_state

logger = logging.getLogger(__name__)

CACHE_DIR = Path("/tmp/slides-cache")
_POLL_DELAY_S = 3.0       # wait before first fingerprint check
_POLL_INTERVAL_S = 3.0    # interval between fingerprint checks
_POLL_TIMEOUT_S = 60.0    # give up after this long
_DOWNLOAD_TIMEOUT_S = 60  # single HTTP download timeout


def _ssl_ctx() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


# ── Daemon log push ────────────────────────────────────────────────────────────

async def _push_log(slug: str, event: str, detail: str = ""):
    """Send a slide_log message to the daemon (if connected) and log locally."""
    logger.info("slide_log slug=%s event=%s detail=%s", slug, event, detail)
    ws = state.daemon_ws
    if ws:
        try:
            await ws.send_json({"type": "slide_log", "slug": slug, "event": event, "detail": detail})
        except Exception:
            pass


# ── Status helpers ─────────────────────────────────────────────────────────────

def _set_status(slug: str, status: str, **extra):
    """Update cache status for a slug and broadcast to host."""
    entry = state.slides_cache_status.get(slug, {})
    entry["status"] = status
    entry["slug"] = slug
    title = state.slides_catalog.get(slug, {}).get("title", slug)
    entry["title"] = title
    entry.update(extra)
    state.slides_cache_status[slug] = entry


def _get_status(slug: str) -> str:
    return state.slides_cache_status.get(slug, {}).get("status", "not_cached")


def _cache_path(slug: str) -> Path:
    return CACHE_DIR / f"{slug}.pdf"


def _get_lock(slug: str) -> asyncio.Lock:
    if slug not in state.slides_gdrive_locks:
        state.slides_gdrive_locks[slug] = asyncio.Lock()
    return state.slides_gdrive_locks[slug]


def _get_event(slug: str) -> asyncio.Event:
    if slug not in state.slides_download_events:
        state.slides_download_events[slug] = asyncio.Event()
    return state.slides_download_events[slug]


# ── GDrive HTTP (runs in executor — sync) ─────────────────────────────────────

def _probe_fingerprint_sync(url: str) -> str:
    """Probe GDrive URL for fingerprint. HEAD first, GET+SHA256 fallback."""
    ctx = _ssl_ctx()
    # Try HEAD
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            etag = hdrs.get("etag", "").strip()
            lm = hdrs.get("last-modified", "").strip()
            cl = hdrs.get("content-length", "").strip()
            if etag or lm or cl:
                return f"hdr:{etag}|{lm}|{cl}"
    except urllib.error.HTTPError as exc:
        if exc.code != 405:
            raise
    except urllib.error.URLError:
        raise
    # Fallback: GET + SHA256
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT_S, context=ctx) as resp:
        payload = resp.read()
    return f"body:{hashlib.sha256(payload).hexdigest()}"


def _download_pdf_sync(url: str, dest: Path) -> int:
    """Download PDF from GDrive URL. Returns size in bytes. Raises on non-PDF."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    ctx = _ssl_ctx()
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT_S, context=ctx) as resp:
        payload = resp.read()
    if not payload or not payload.startswith(b"%PDF"):
        raise RuntimeError("Response is not a PDF")
    dest.write_bytes(payload)
    return len(payload)


# ── Async wrappers ─────────────────────────────────────────────────────────────

async def _probe_fingerprint(url: str) -> str:
    return await asyncio.get_event_loop().run_in_executor(None, _probe_fingerprint_sync, url)


async def _download_pdf(url: str, dest: Path) -> int:
    return await asyncio.get_event_loop().run_in_executor(None, _download_pdf_sync, url, dest)


# ── Core download (per-slug locked) ───────────────────────────────────────────

async def _do_download(slug: str, url: str) -> Path:
    """Download a PDF, guarded by per-slug lock + global semaphore. Returns cache path."""
    lock = _get_lock(slug)
    dest = _cache_path(slug)
    async with lock:
        async with state.slides_download_semaphore:
            _set_status(slug, "downloading")
            await broadcast_state()
            await _push_log(slug, "download_started", f"url={url}")
            t0 = time.monotonic()
            try:
                size = await _download_pdf(url, dest)
            except Exception as exc:
                _set_status(slug, "download_failed")
                await broadcast_state()
                await _push_log(slug, "download_failed", str(exc))
                raise
            elapsed = round(time.monotonic() - t0, 1)
            size_mb = round(size / 1048576, 1)
            # Save fingerprint for future invalidation checks
            try:
                fp = await _probe_fingerprint(url)
                state.slides_fingerprints[slug] = fp
            except Exception:
                pass
            _set_status(slug, "cached", size_bytes=size,
                        downloaded_at=datetime.now(timezone.utc).isoformat())
            await broadcast_state()
            await _push_log(slug, "download_complete", f"size={size_mb}MB elapsed={elapsed}s")
    return dest


# ── Public: serve or download on demand ────────────────────────────────────────

async def download_or_wait_cached(slug: str) -> Path | None:
    """
    Return the cached PDF path for a slug. Downloads from GDrive if needed.
    Multiple concurrent callers for the same slug: only one downloads, others wait.
    Returns None if no catalog entry or download fails.

    Race-condition safe: uses per-slug lock to ensure exactly one download initiator.
    """
    dest = _cache_path(slug)
    if dest.exists():
        return dest

    entry = state.slides_catalog.get(slug)
    if not entry or not entry.get("drive_export_url"):
        return None

    url = entry["drive_export_url"]
    lock = _get_lock(slug)

    # Try to acquire the lock without blocking to determine role (initiator vs waiter)
    if lock.locked():
        # Another coroutine is already downloading — just wait for the event
        event = _get_event(slug)
        try:
            await asyncio.wait_for(event.wait(), timeout=60)
        except asyncio.TimeoutError:
            return None
        return dest if dest.exists() else None

    # We might be the initiator — acquire lock (may briefly contend)
    event = _get_event(slug)
    event.clear()
    try:
        path = await _do_download(slug, url)
        event.set()
        return path
    except Exception:
        event.set()  # unblock waiters even on failure
        return dest if dest.exists() else None  # serve stale if available


# ── Invalidation: fingerprint poll loop ────────────────────────────────────────

async def handle_slide_invalidated(slug: str):
    """Called when daemon reports a PPTX changed. Starts fingerprint polling."""
    current = _get_status(slug)
    if current in ("polling_drive", "downloading"):
        logger.info("slide_invalidated slug=%s ignored (status=%s)", slug, current)
        return

    entry = state.slides_catalog.get(slug)
    if not entry or not entry.get("drive_export_url"):
        return

    url = entry["drive_export_url"]
    has_cached = _cache_path(slug).exists()
    _set_status(slug, "stale" if has_cached else "not_cached")
    await broadcast_state()
    await _push_log(slug, "invalidated")

    # Start poll loop as a background task
    asyncio.create_task(_poll_fingerprint_loop(slug, url))


async def _poll_fingerprint_loop(slug: str, url: str):
    """Poll GDrive fingerprint until it changes, then re-download."""
    lock = _get_lock(slug)
    old_fp = state.slides_fingerprints.get(slug)

    # If no baseline fingerprint, fetch one now
    if not old_fp:
        try:
            async with lock:
                old_fp = await _probe_fingerprint(url)
            state.slides_fingerprints[slug] = old_fp
        except Exception as exc:
            await _push_log(slug, "poll_started", f"fingerprint_fetch_failed: {exc}")
            _set_status(slug, "poll_timeout")
            await broadcast_state()
            return

    _set_status(slug, "polling_drive")
    await broadcast_state()
    await _push_log(slug, "poll_started", f"fingerprint={old_fp}")

    await asyncio.sleep(_POLL_DELAY_S)

    deadline = time.monotonic() + _POLL_TIMEOUT_S
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        try:
            async with lock:
                new_fp = await _probe_fingerprint(url)
            await _push_log(slug, "poll_check", f"attempt={attempt} fingerprint={new_fp}")
            if new_fp != old_fp:
                await _push_log(slug, "poll_fingerprint_changed", f"old={old_fp} new={new_fp}")
                # Re-download
                event = _get_event(slug)
                event.clear()
                try:
                    await _do_download(slug, url)
                except Exception:
                    pass
                event.set()
                return
        except Exception as exc:
            await _push_log(slug, "poll_check", f"attempt={attempt} error={exc}")
        await asyncio.sleep(_POLL_INTERVAL_S)

    _set_status(slug, "poll_timeout")
    await broadcast_state()
    await _push_log(slug, "poll_timeout", f"attempts={attempt}")


# ── Catalog management ─────────────────────────────────────────────────────────

async def handle_slides_catalog(entries: list[dict]):
    """Called when daemon sends slides_catalog message."""
    state.slides_catalog = {e["slug"]: e for e in entries if e.get("slug")}
    # Initialize status for new slugs
    for slug in state.slides_catalog:
        if slug not in state.slides_cache_status:
            cached = _cache_path(slug).exists()
            _set_status(slug, "cached" if cached else "not_cached")
    await broadcast_state()
    await _push_log("*", "catalog_received", f"entries={len(state.slides_catalog)}")
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/features/slides/test_cache.py -v`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add features/slides/cache.py tests/features/slides/test_cache.py
git commit -m "feat(slides): add server-side PDF cache with GDrive download + fingerprint polling"
```

---

### Task 4: Wire cache into WebSocket daemon handler

**Files:**
- Modify: `features/ws/router.py` (~lines 86-96 daemon message handling)

- [ ] **Step 1: Read `features/ws/router.py`** to find exact line numbers.

- [ ] **Step 2: Replace `slides_meta` and `slides_upload_result` handlers**

In the daemon WS handler's message loop, replace:

```python
if msg_type == "slides_upload_result":
    from features.slides.drive_status import register_daemon_upload_result
    await register_daemon_upload_result(data)
elif msg_type == "slides_meta":
    state.slides_meta = {
        s["slug"]: s["updated_at"]
        for s in data.get("slides", [])
        if s.get("slug") and s.get("updated_at")
    }
```

With:

```python
if msg_type == "slides_catalog":
    from features.slides.cache import handle_slides_catalog
    await handle_slides_catalog(data.get("entries", []))
elif msg_type == "slide_invalidated":
    from features.slides.cache import handle_slide_invalidated
    slug = data.get("slug", "").strip()
    if slug:
        await handle_slide_invalidated(slug)
```

- [ ] **Step 3: Verify server starts** (same curl check).

- [ ] **Step 4: Commit**

```bash
git add features/ws/router.py
git commit -m "feat(ws): handle slides_catalog and slide_invalidated, remove old upload_result/meta"
```

---

### Task 5: Modify slide file serving to use cache

**Files:**
- Modify: `features/slides/router.py` (~lines 418-441 `GET /api/slides/file/{slug}`)

- [ ] **Step 1: Read `features/slides/router.py`** lines 410-445 for the current `GET /api/slides/file/{slug}` endpoint.

- [ ] **Step 2: Rewrite the endpoint to serve from cache**

The current flow: look in local/uploaded dirs → on-demand daemon upload → serve. New flow: look in local/uploaded dirs → look in cache dir → trigger GDrive download → serve.

```python
@public_router.get("/api/slides/file/{slug}")
@public_router.head("/api/slides/file/{slug}")
async def serve_slide_file(slug: str, request: Request):
    # 1. Check local / uploaded (existing logic — _resolve_slide_path)
    path = _resolve_slide_path(slug)

    # 2. Check cache dir
    if not path:
        from features.slides.cache import _cache_path
        cached = _cache_path(slug)
        if cached.exists():
            path = cached

    # 3. On-demand GDrive download
    if not path:
        from features.slides.cache import download_or_wait_cached
        path = await download_or_wait_cached(slug)

    if not path or not path.exists():
        raise HTTPException(status_code=404, detail="Slide not found")

    # ETag / Last-Modified / 304 handling (existing logic — note: _is_not_modified takes 3 args)
    etag = _slide_etag(path)
    if _is_not_modified(request, etag, path):
        return Response(status_code=304)
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={
            "ETag": etag,
            "Last-Modified": _slide_last_modified(path),
            "Cache-Control": "no-cache",
        },
    )
```

Also remove the import of `_wait_for_slide_upload` and `_on_demand_enabled` from `drive_status`.

- [ ] **Step 3: Remove `drive_status.py` router inclusion** — in `router.py` remove the import of `router as drive_status_router`, `_wait_for_slide_upload`, and `_on_demand_enabled` from `drive_status`. Remove any `include_router(drive_status_router)` calls. The `GET /api/slides/participant-availability` endpoint is no longer needed (host popover now uses WS-pushed state). The `GET /api/slides/upload-status/{slug}` endpoint is also removed.

- [ ] **Step 4: Update `slides_meta` references in `router.py`** — search for `state.slides_meta` in `router.py` (~line 272 in `_collect_participant_slides`). Replace `slides_meta` usage with `slides_catalog` data. For example, the sync status check should use `state.slides_cache_status.get(slug, {}).get("status")` instead of `slides_meta`.

- [ ] **Step 5: Update `GET /api/slides` availability logic** — the `GET /api/slides` endpoint (~lines 405-415) currently uses `_on_demand_enabled()` and `state.daemon_ws is not None` to set `available_on_server`. Change this: a slide is `available_on_server` if it exists locally/uploaded OR if it exists in the cache dir (`/tmp/slides-cache/{slug}.pdf`) OR if it's in the catalog (downloadable on demand).

- [ ] **Step 6: Verify server starts** (same curl check).

- [ ] **Step 7: Commit**

```bash
git add features/slides/router.py
git commit -m "feat(slides): serve PDFs from cache, on-demand GDrive download, remove slides_meta refs"
```

---

### Task 6: Update state builder to push cache status to host

**Files:**
- Modify: `features/slides/state_builder.py` (lines 14-20)

- [ ] **Step 1: Read `features/slides/state_builder.py`** for exact current content.

- [ ] **Step 2: Add `slides_cache_status` to host state**

```python
def build_for_host():
    return {
        "slides_current": state.slides_current,
        "slides_cache_status": state.slides_cache_status,
        "session_main": getattr(state, "session_main", None),
        "session_talk": getattr(state, "session_talk", None),
        "session_name": getattr(state, "session_name", None),
    }
```

- [ ] **Step 3: Commit**

```bash
git add features/slides/state_builder.py
git commit -m "feat(slides): push cache status to host via WS state"
```

---

### Task 7: Update host UI 📜 popover to render cache status

**Files:**
- Modify: `static/host.js` (~lines 856-918, the `_renderSlidesCatalogPopover` and `_loadSlidesCatalogMap` functions)
- Modify: `static/host.css` (if needed for status label styling)

- [ ] **Step 1: Read `static/host.js`** lines 850-940 for the current popover rendering logic.

- [ ] **Step 2: Rewrite `_renderSlidesCatalogPopover()` to use WS-pushed state**

The popover should now render from `_lastHostState.slides_cache_status` (pushed via WS) instead of fetching from an HTTP endpoint. This eliminates the need for `_loadSlidesCatalogMap()`.

```javascript
function _renderSlidesCatalogPopover() {
    const el = document.getElementById('slides-catalog-content');
    const cacheStatus = (_lastHostState && _lastHostState.slides_cache_status) || {};
    const entries = Object.values(cacheStatus);

    if (!entries.length) {
        el.innerHTML = '<div style="padding:8px;opacity:0.5">No slides in catalog</div>';
        return;
    }

    const statusConfig = {
        'cached':         { icon: '🟢', label: 'cached',     color: 'var(--ok, #4caf50)' },
        'downloading':    { icon: '🔄', label: 'syncing',    color: 'var(--info, #2196f3)' },
        'polling_drive':  { icon: '🔄', label: 'syncing',    color: 'var(--info, #2196f3)' },
        'stale':          { icon: '🟡', label: 'stale',      color: 'var(--warn, #ff9800)' },
        'not_cached':     { icon: '🔴', label: 'not cached', color: 'var(--danger, #f44336)' },
        'poll_timeout':   { icon: '⚠',  label: 'timeout',    color: 'var(--warn, #ff9800)' },
        'download_failed':{ icon: '❌', label: 'failed',     color: 'var(--danger, #f44336)' },
    };

    // Sort: cached first, then by title
    entries.sort((a, b) => {
        const ao = a.status === 'cached' ? 0 : 1;
        const bo = b.status === 'cached' ? 0 : 1;
        return ao - bo || (a.title || '').localeCompare(b.title || '');
    });

    const cachedCount = entries.filter(e => e.status === 'cached').length;
    let html = `<div class="slides-catalog-header">${cachedCount}/${entries.length} cached</div>`;

    for (const entry of entries) {
        const cfg = statusConfig[entry.status] || statusConfig['not_cached'];
        const title = entry.title || entry.slug;
        const sizePart = entry.size_bytes ? `${(entry.size_bytes / 1048576).toFixed(1)} MB` : '';
        const agePart = entry.downloaded_at ? _formatAge(entry.downloaded_at) : '';
        const detail = [sizePart, agePart].filter(Boolean).join('  ');
        html += `<div class="slides-catalog-line">
            <span class="slides-cache-icon">${cfg.icon}</span>
            <span class="slides-cache-label" style="color:${cfg.color}">${cfg.label}</span>
            <span class="slides-cache-title">${_esc(title)}</span>
            <span class="slides-cache-detail">${detail}</span>
        </div>`;
    }
    el.innerHTML = html;
}

function _formatAge(isoStr) {
    const ms = Date.now() - new Date(isoStr).getTime();
    if (ms < 60000) return 'just now';
    if (ms < 3600000) return Math.floor(ms / 60000) + 'm ago';
    return Math.floor(ms / 3600000) + 'h ago';
}
```

- [ ] **Step 3: Update hover handler** to call `_renderSlidesCatalogPopover()` on hover (no HTTP fetch needed). Remove `_loadSlidesCatalogMap()` and its TTL logic. Call `_renderSlidesCatalogPopover()` whenever WS state arrives (in the state update handler).

- [ ] **Step 4: Add CSS for the new layout** (in `static/host.css`):

```css
.slides-cache-icon { width: 20px; text-align: center; flex-shrink: 0; }
.slides-cache-label { width: 70px; font-size: 0.8em; flex-shrink: 0; }
.slides-cache-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.slides-cache-detail { font-size: 0.75em; opacity: 0.6; flex-shrink: 0; margin-left: 8px; }
```

- [ ] **Step 5: Test in browser** — start local server, open `/host`, hover over 📜 icon. Verify popover renders (will be empty without daemon, but should show "No slides in catalog").

- [ ] **Step 6: Commit**

```bash
git add static/host.js static/host.css
git commit -m "feat(host): render slides cache status in popover from WS state"
```

---

### Task 8: Modify daemon — send `slides_catalog` on connect, handle `slide_log`

**Files:**
- Modify: `daemon/materials/ws_runner.py` (~lines 177-259 `_handle_request`, `_send_slides_meta`, `_run_loop`)

- [ ] **Step 1: Read `daemon/materials/ws_runner.py`** for exact current content of `_send_slides_meta()`, `_handle_request()`, and `_run_loop()`.

- [ ] **Step 2: Replace `_send_slides_meta` with `_send_slides_catalog`**

Instead of sending `{type: "slides_meta", slides: [{slug, updated_at}]}`, send `{type: "slides_catalog", entries: [{slug, title, drive_export_url}]}` using data from the catalog JSON file.

```python
def _send_slides_catalog(self, ws) -> None:
    """Send full catalog with drive_export_url to backend."""
    try:
        catalog_path = self._catalog_path()
        if not catalog_path.exists():
            log.info("slides", "slides_catalog: no catalog file found")
            return
        import json
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
        entries = []
        for deck in data.get("decks", []):
            slug = deck.get("slug") or _slugify(deck.get("title", ""))
            url = deck.get("drive_export_url", "")
            if slug and url:
                entries.append({"slug": slug, "title": deck.get("title", slug), "drive_export_url": url})
        ws.send(json.dumps({"type": "slides_catalog", "entries": entries}))
        log.info("slides", f"slides_catalog sent: {len(entries)} entries")
    except Exception as exc:
        log.error("slides", f"slides_catalog_send_failed: {exc}")
```

- [ ] **Step 3: Handle `slide_log` messages in `_handle_request`**

```python
if payload.get("type") == "slide_log":
    slug = payload.get("slug", "?")
    event = payload.get("event", "?")
    detail = payload.get("detail", "")
    log.info("slides", f"📡 {event} slug={slug} {detail}")
    return
```

- [ ] **Step 4: Remove `slides_upload_request` handling** from `_handle_request()`. Remove the `post_material_upsert_file` import and usage. The daemon no longer uploads PDFs to the backend.

- [ ] **Step 5: Update `_run_loop`** to call `_send_slides_catalog(ws)` instead of `_send_slides_meta(ws)` on connect.

- [ ] **Step 6: Remove `_send_slides_meta` method** entirely.

- [ ] **Step 7: Remove `server_ping` and `drive_download_result` handlers** (PoC artifacts).

- [ ] **Step 8: Commit**

```bash
git add daemon/materials/ws_runner.py
git commit -m "feat(daemon): send slides_catalog on connect, handle slide_log, remove upload logic"
```

---

### Task 9: Modify daemon — PPTX change sends `slide_invalidated` instead of converting

**Files:**
- Modify: `daemon/slides/loop.py`
- Reference: `daemon/slides/daemon.py`, `daemon/slides/upload.py` (to understand current flow)

- [ ] **Step 1: Read `daemon/slides/loop.py`** and `daemon/slides/daemon.py` to understand the current PPTX change detection → conversion → upload flow.

- [ ] **Step 2: Modify `SlidesPollingRunner`** to send `slide_invalidated` via daemon WS instead of triggering conversion/upload.

The runner needs access to the daemon's WebSocket. Since `ws_runner.py`'s `SlidesOnDemandWsRunner` maintains the WS connection, the polling runner should send invalidation messages through it.

Simplest approach: when a PPTX change is detected, call a callback that sends the WS message. The main daemon can wire this up.

- [ ] **Step 3: Commit**

```bash
git add daemon/slides/loop.py
git commit -m "feat(daemon): send slide_invalidated on PPTX change instead of converting"
```

---

### Task 10: Remove `drive_status.py` and clean up dead code

**Files:**
- Remove: `features/slides/drive_status.py`
- Modify: `features/slides/router.py` (remove imports)
- Modify: `features/slides/__init__.py` (if it re-exports anything)

- [ ] **Step 1: Search for all references to `drive_status`**

Run: `grep -r "drive_status" features/ --include="*.py"` and fix all imports.

- [ ] **Step 2: Move `participant-availability` endpoint** if needed — check if `GET /api/slides/participant-availability` (in `drive_status.py`) is used by the host UI popover. If the new popover uses WS-pushed state (Task 7), this endpoint may no longer be needed. If still needed, move it to `router.py`.

- [ ] **Step 3: Delete `features/slides/drive_status.py`**

- [ ] **Step 4: Remove `slides_uploads` references** — search for `slides_uploads` across the codebase and remove any remaining references.

- [ ] **Step 5: Run existing tests**

Run: `pytest tests/features/slides/ -v`
Expected: All pass (with updated imports).

- [ ] **Step 6: Commit**

```bash
git add -A features/slides/
git commit -m "chore: remove drive_status.py and old on-demand upload code"
```

---

### Task 11: Integration test — full flow

**Files:**
- Create or modify: `tests/features/slides/test_cache.py` (add integration tests)

- [ ] **Step 1: Write integration test** using the test server fixture from `conftest.py`.

Test the full flow:
1. Start test server
2. Simulate daemon WS connect → send `slides_catalog` with a test entry (use a mock HTTP server for the GDrive URL)
3. Request `GET /api/slides/file/{slug}` — assert it downloads and serves the PDF
4. Request the same slug again — assert it serves from cache (no second download)
5. Simulate `slide_invalidated` → assert status transitions
6. Verify host state includes `slides_cache_status`

Use `httpx` for HTTP calls and `websockets` for WS simulation.

- [ ] **Step 2: Run integration tests**

Run: `pytest tests/features/slides/test_cache.py -v`
Expected: All pass.

- [ ] **Step 3: Run ALL existing tests** to verify nothing is broken.

Run: `pytest tests/ -v --ignore=tests/load`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test(slides): integration tests for server-side PDF cache"
```

---

### Task 12: Push to master and verify deployment

- [ ] **Step 1: Rebase on origin/master**

```bash
git fetch origin master && git rebase origin/master
```

- [ ] **Step 2: Push**

```bash
git push origin HEAD:master
```

- [ ] **Step 3: Verify deployment** — check Railway logs for successful startup. Check `/api/status` on prod. Start daemon and verify it sends `slides_catalog` and receives `slide_log` messages.

- [ ] **Step 4: Manual smoke test** — open participant page, request a slide that requires GDrive download. Verify it loads. Check host 📜 popover shows status.
