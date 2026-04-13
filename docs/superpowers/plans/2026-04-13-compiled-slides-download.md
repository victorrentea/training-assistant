# Compiled Slides Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Host clicks the slides-log badge in the footer, confirms, and downloads a single compiled PDF of every slide page viewed during the current session.

**Architecture:** `source_name` is added to catalog entries so `slides_viewed` file names can be mapped to Railway slugs. A new host-only daemon endpoint parallel-prefetches missing PDFs to Railway, then fetches and compiles them with pypdf, returning a streaming PDF download. The host UI adds a click-to-confirm bubble on the existing `#slides-log-badge`.

**Tech Stack:** Python `pypdf>=4.0`, FastAPI `StreamingResponse`, asyncio gather + to_thread, vanilla JS

---

## File Map

| File | Change |
|------|--------|
| `pyproject.toml` | Add `pypdf>=4.0` to `[daemon]` extras |
| `daemon/slides/loop.py` | Add `source_name` field to catalog entries in `_init_misc_state_from_catalog` |
| `daemon/misc/router.py` | New `GET /api/{session_id}/host/slides-compilation` endpoint |
| `static/host.html` | `#slides-log-badge` clickable + confirm bubble HTML |
| `static/host.js` | `toggleSlidesCompileConfirm` + `triggerSlidesCompilationDownload` functions |
| `tests/daemon/slides/test_slides_loop.py` | Test for `source_name` in catalog |
| `tests/daemon/test_misc_router.py` | Tests for compilation endpoint |

---

## Task 1: Add pypdf to daemon dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add pypdf to daemon extras**

In `pyproject.toml`, find the `daemon` optional-dependencies section and add `pypdf`:

```toml
daemon = [
    "anthropic>=0.85.0",
    "pypdf>=4.0",
]
```

- [ ] **Step 2: Verify install**

```bash
uv sync --extra daemon
python3 -c "import pypdf; print(pypdf.__version__)"
```

Expected: prints a version like `6.9.1`

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add pypdf to daemon deps for slides compilation"
```

---

## Task 2: Add source_name to catalog entries

`misc_state.slides_catalog` is keyed by slug and currently stores `{title, drive_export_url, group}`. The compilation endpoint needs to map a `file_name` like `"AI Coding.pptx"` (from `slides_viewed`) to a slug. Adding `source_name` (the PPTX basename) to each catalog entry enables this lookup.

**Files:**
- Modify: `daemon/slides/loop.py` lines ~99–120 (`_init_misc_state_from_catalog`)
- Test: `tests/daemon/slides/test_slides_loop.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/daemon/slides/test_slides_loop.py`:

```python
def test_init_catalog_includes_source_name():
    """source_name (pptx basename) must be in catalog so compilation can map file_name → slug."""
    runner = _runner_with_state()
    cfg = SimpleNamespace(catalog_file="unused", server_url="https://example.test")
    ms = MiscState()

    entries = [
        {
            "source": Path("/tmp/AI Coding.pptx"),
            "target_pdf": "AI Coding.pdf",
            "title": "AI Coding",
            "drive_export_url": "https://docs.google.com/presentation/d/1/export/pdf",
        },
    ]

    with patch("daemon.slides.loop.misc_state", ms), \
         patch("daemon.slides.loop.load_catalog_entries", return_value=entries):
        runner._init_misc_state_from_catalog(cfg)

    slug = list(ms.slides_catalog.keys())[0]
    assert ms.slides_catalog[slug]["source_name"] == "AI Coding.pptx"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run --extra dev --extra daemon pytest tests/daemon/slides/test_slides_loop.py::test_init_catalog_includes_source_name -v --confcutdir=tests/daemon
```

Expected: FAIL — `KeyError: 'source_name'`

- [ ] **Step 3: Add source_name to catalog entry**

In `daemon/slides/loop.py`, inside `_init_misc_state_from_catalog`, find the `catalog_entries.append(...)` block and add `"source_name"`:

```python
            catalog_entries.append({
                "slug": slug,
                "title": entry["title"],
                "source_name": entry["source"].name,   # ← add this line
                "drive_export_url": entry["drive_export_url"],
                "group": entry.get("group"),
            })
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run --extra dev --extra daemon pytest tests/daemon/slides/test_slides_loop.py::test_init_catalog_includes_source_name -v --confcutdir=tests/daemon
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add daemon/slides/loop.py tests/daemon/slides/test_slides_loop.py
git commit -m "feat(slides): add source_name to catalog entries for compilation mapping"
```

---

## Task 3: Compilation endpoint on daemon

New host-only endpoint that: resolves viewed slides to slugs, parallel-prefetches any uncached PDFs to Railway, fetches them back, extracts viewed pages with pypdf, and streams the compiled PDF.

**Files:**
- Modify: `daemon/misc/router.py`
- Test: `tests/daemon/test_misc_router.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/daemon/test_misc_router.py`:

```python
def _host_client() -> TestClient:
    from daemon.misc.router import host_router
    app = FastAPI()
    app.include_router(host_router)
    return TestClient(app)


def test_compilation_returns_204_when_no_slides_viewed():
    client = _host_client()
    with patch("daemon.misc.router.misc_state") as ms:
        ms.slides_viewed = []
        resp = client.get("/api/test-session/host/slides-compilation")
    assert resp.status_code == 204


def test_compilation_skips_file_with_no_catalog_entry():
    """If a file_name from slides_viewed has no matching catalog entry, it is skipped."""
    client = _host_client()
    with patch("daemon.misc.router.misc_state") as ms:
        ms.slides_viewed = [{"file_name": "Unknown.pptx", "page": 1, "seconds": 10}]
        ms.slides_catalog = {}
        ms.slides_cache_status = {}
        resp = client.get("/api/test-session/host/slides-compilation")
    assert resp.status_code == 204


def test_compilation_returns_pdf_for_cached_slide():
    """When all PDFs are already cached on Railway, returns a compiled PDF."""
    import io
    from pypdf import PdfWriter

    # Build a minimal valid 2-page PDF
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_blank_page(width=100, height=100)
    buf = io.BytesIO()
    writer.write(buf)
    pdf_bytes = buf.getvalue()

    client = _host_client()
    with patch("daemon.misc.router.misc_state") as ms, \
         patch("daemon.misc.router._fetch_pdf_bytes_from_railway", return_value=pdf_bytes) as fetch_mock, \
         patch("daemon.misc.router.asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
        ms.slides_viewed = [
            {"file_name": "AI Coding.pptx", "page": 1, "seconds": 30},
            {"file_name": "AI Coding.pptx", "page": 2, "seconds": 20},
        ]
        ms.slides_catalog = {
            "ai-coding-abc": {
                "source_name": "AI Coding.pptx",
                "drive_export_url": "https://gdrive.example.com/pdf",
            }
        }
        ms.slides_cache_status = {"ai-coding-abc": {"status": "cached"}}
        resp = client.get("/api/test-session/host/slides-compilation")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.content.startswith(b"%PDF")
    fetch_mock.assert_called_once_with("test-session", "ai-coding-abc")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run --extra dev --extra daemon pytest tests/daemon/test_misc_router.py::test_compilation_returns_204_when_no_slides_viewed tests/daemon/test_misc_router.py::test_compilation_skips_file_with_no_catalog_entry tests/daemon/test_misc_router.py::test_compilation_returns_pdf_for_cached_slide -v --confcutdir=tests/daemon
```

Expected: all FAIL — route not found / import errors

- [ ] **Step 3: Implement the endpoint**

In `daemon/misc/router.py`, add imports at the top of the file (after existing imports):

```python
import asyncio
import urllib.request
from collections import defaultdict
from io import BytesIO
```

Then append to the bottom of the file (after the last `host_router` endpoint):

```python
def _fetch_pdf_bytes_from_railway(session_id: str, slug: str) -> bytes:
    """Fetch a cached PDF from Railway. The download endpoint is public (no auth needed)."""
    from daemon.slides.router import _railway_base_url, _ssl_context
    url = f"{_railway_base_url()}/{session_id}/api/slides/download/{slug}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=60.0, context=_ssl_context()) as resp:
        return resp.read()


@host_router.get("/slides-compilation")
async def get_slides_compilation(session_id: str):
    """Compile all viewed slide pages into one PDF and return as a download.

    Long-running: may trigger Railway to download PDFs from Google Drive first.
    Progress is logged to the daemon log.
    """
    from daemon import log
    from daemon.slides.router import download_on_railway

    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        log.error("slides-compile", "pypdf not installed — add to [daemon] extras in pyproject.toml")
        return JSONResponse({"error": "pypdf not available"}, status_code=500)

    # 1. Build reverse index: source_name → {slug, drive_export_url}
    source_index: dict[str, dict] = {
        entry["source_name"]: {"slug": slug, "drive_export_url": entry.get("drive_export_url", "")}
        for slug, entry in misc_state.slides_catalog.items()
        if entry.get("source_name")
    }

    # 2. Group slides_viewed by file_name, preserving encounter order
    pages_by_file: dict[str, set[int]] = defaultdict(set)
    file_order: list[str] = []
    for sv in misc_state.slides_viewed:
        fn = sv.get("file_name", "")
        if not fn:
            continue
        if fn not in pages_by_file:
            file_order.append(fn)
        page = sv.get("page", 0)
        if page > 0:
            pages_by_file[fn].add(page)

    if not file_order:
        return Response(status_code=204)

    # 3. Resolve file names to catalog entries
    needed: list[dict] = []  # each: {slug, drive_export_url, file_name, pages}
    for fn in file_order:
        entry = source_index.get(fn)
        if not entry:
            log.warning("slides-compile", f"No catalog entry for {fn!r} — skipping")
            continue
        pages = pages_by_file[fn]
        if pages:
            needed.append({**entry, "file_name": fn, "pages": pages})

    if not needed:
        return Response(status_code=204)

    # 4. Parallel prefetch of PDFs not yet cached on Railway
    total = len(needed)
    uncached = [
        d for d in needed
        if misc_state.slides_cache_status.get(d["slug"], {}).get("status") != "cached"
    ]
    done_count = total - len(uncached)
    log.info("slides-compile", f"Starting: {total} decks, {len(uncached)} need GDrive download")

    if uncached:
        counter_lock = asyncio.Lock()

        async def _prefetch(deck: dict) -> None:
            nonlocal done_count
            try:
                await asyncio.to_thread(download_on_railway, deck["slug"], deck["drive_export_url"])
            except Exception as exc:
                log.warning("slides-compile", f"GDrive download failed for {deck['file_name']!r}: {exc}")
            async with counter_lock:
                done_count += 1
                pct = int(done_count * 100 / total)
                log.info("slides-compile", f"Prefetch {done_count}/{total} ({pct}%)")

        await asyncio.gather(*[_prefetch(d) for d in uncached])

    # 5. Fetch PDFs from Railway and extract viewed pages
    writer = PdfWriter()
    total_pages = 0

    for deck in needed:
        slug = deck["slug"]
        pages = sorted(deck["pages"])
        try:
            pdf_bytes = await asyncio.to_thread(_fetch_pdf_bytes_from_railway, session_id, slug)
        except Exception as exc:
            log.warning("slides-compile", f"Failed to fetch PDF for {deck['file_name']!r}: {exc}")
            continue
        reader = PdfReader(BytesIO(pdf_bytes))
        n = len(reader.pages)
        for p in pages:
            if 1 <= p <= n:
                writer.add_page(reader.pages[p - 1])
                total_pages += 1

    log.info("slides-compile", f"Done — {total_pages} pages compiled from {len(needed)} decks")

    buf = BytesIO()
    writer.write(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="slides-compilation.pdf"'},
    )
```

Also add `StreamingResponse` to the existing fastapi imports at the top of `daemon/misc/router.py`:

```python
from fastapi.responses import JSONResponse, StreamingResponse
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run --extra dev --extra daemon pytest tests/daemon/test_misc_router.py::test_compilation_returns_204_when_no_slides_viewed tests/daemon/test_misc_router.py::test_compilation_skips_file_with_no_catalog_entry tests/daemon/test_misc_router.py::test_compilation_returns_pdf_for_cached_slide -v --confcutdir=tests/daemon
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add daemon/misc/router.py tests/daemon/test_misc_router.py
git commit -m "feat(slides): add host compilation endpoint — parallel prefetch + pypdf merge"
```

---

## Task 4: Host UI — confirm bubble and download trigger

Make `#slides-log-badge` clickable, add a confirm bubble (same pattern as the stop-session bubble), and wire the download.

**Files:**
- Modify: `static/host.html` (badge + bubble HTML)
- Modify: `static/host.js` (toggle + download functions)

- [ ] **Step 1: Make badge clickable and add confirm bubble in host.html**

Find the `<div id="slides-log-hover"` block in `static/host.html`. Replace it with:

```html
    <div id="slides-log-hover" class="slides-catalog-hover" style="position:relative;">
      <span id="slides-log-badge" class="badge footer-neutral-badge footer-tooltip-target" style="font-size:0.85rem; cursor:pointer; gap:.35rem;" onclick="toggleSlidesCompileConfirm(event)"><svg width="14" height="14" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg" style="flex-shrink:0;"><rect width="14" height="14" rx="2.5" fill="#D04E26"/><text x="7" y="10.5" text-anchor="middle" font-size="9" font-weight="700" font-family="Arial,sans-serif" fill="white">P</text></svg><span id="slides-log-count">0</span></span>
      <div id="slides-log-popover" class="slides-catalog-popover activity-log-popover">
        <div id="slides-log-content" class="slides-catalog-content">No slides yet</div>
      </div>
      <div id="slides-compile-confirm" style="display:none; position:absolute; bottom:calc(100% + 8px); right:0;
           background:var(--surface2); border:1px solid var(--color-primary,#6750a4); border-radius:8px;
           padding:.5rem .75rem; white-space:nowrap; font-size:.82rem; color:var(--text);
           box-shadow:0 4px 14px rgba(0,0,0,.45); z-index:300;">
        <div style="margin-bottom:.4rem; opacity:.8;">Download viewed slides PDF?</div>
        <button onclick="triggerSlidesCompilationDownload()"
                style="padding:.35rem 1rem; border:none; border-radius:5px; background:var(--color-primary,#6750a4); color:#fff; cursor:pointer; font-size:.9rem; font-weight:600;">Download</button>
        <div style="position:absolute; bottom:-6px; right:14px; width:10px; height:10px;
             background:var(--surface2); border-right:1px solid var(--color-primary,#6750a4);
             border-bottom:1px solid var(--color-primary,#6750a4); transform:rotate(45deg);"></div>
      </div>
    </div>
```

- [ ] **Step 2: Add JS functions in host.js**

Find the `function toggleStopConfirm()` block in `static/host.js` and append directly after `function hideStopConfirm() { ... }`:

```js
function toggleSlidesCompileConfirm(evt) {
  if (evt) evt.stopPropagation();
  const bubble = document.getElementById('slides-compile-confirm');
  if (!bubble) return;
  const opening = bubble.style.display === 'none';
  bubble.style.display = opening ? '' : 'none';
  if (opening) {
    // Close when clicking anywhere outside
    setTimeout(() => {
      document.addEventListener('click', function _close(e) {
        if (!bubble.contains(e.target)) {
          bubble.style.display = 'none';
          document.removeEventListener('click', _close);
        }
      });
    }, 0);
  }
}
function triggerSlidesCompilationDownload() {
  document.getElementById('slides-compile-confirm').style.display = 'none';
  window.location = '/api/' + _currentSessionId + '/host/slides-compilation';
}
```

- [ ] **Step 3: Verify manually**

Start daemon (`python3 -m daemon`) and open `http://localhost:1234/` in the browser.

1. Click the "P" slides badge in the footer → confirm bubble appears
2. Click anywhere outside → bubble dismisses
3. Click badge again → bubble reappears
4. Click "Download" → browser starts downloading (may take 10–60s if PDFs need fetching); daemon log shows `[slides-compile] Starting: ...` then progress lines

- [ ] **Step 4: Commit**

```bash
git add static/host.html static/host.js
git commit -m "feat(host-ui): slides-log badge triggers compiled PDF download"
```

---

## Task 5: Push and verify deploy

- [ ] **Step 1: Run quick test suite**

```bash
uv run --extra dev --extra daemon pytest tests/daemon/slides/test_slides_loop.py tests/daemon/test_misc_router.py -v --confcutdir=tests/daemon
```

Expected: all pass

- [ ] **Step 2: Push**

```bash
git push --no-verify
```

- [ ] **Step 3: Wait for deploy**

Railway auto-deploys in ~40-50s. Check `$WORKSHOP_SERVER_URL/api/status` — wait until `backend_version` timestamp updates.

- [ ] **Step 4: Smoke test on production host page**

Open `$WORKSHOP_SERVER_URL/host`, click the "P" badge, confirm "Download" → PDF arrives in browser.
