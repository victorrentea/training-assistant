# Compiled Slides Download — Design Spec

**Date:** 2026-04-13  
**Scope:** Host-only. No participant UI changes.

---

## Summary

The host can download a single compiled PDF of every slide page that was actually viewed during the current session. Triggered by clicking the slides-log badge (`#slides-log-badge`, the "P" icon) in the host footer, confirmed via a small inline bubble, then streamed as a file download from the daemon directly to the host browser.

---

## Part 1: Data Mapping (daemon)

### Problem
`misc_state.slides_viewed` entries carry `file_name: "AI Coding.pptx"` (PPTX basename). `misc_state.slides_catalog` is keyed by slug and stores `{title, drive_export_url, group}` — no source filename. There is currently no way to look up a slug from a file name.

### Solution
In `daemon/slides/loop.py :: _init_misc_state_from_catalog`, add `source_name` (the PPTX file basename, e.g. `"AI Coding.pptx"`) to each catalog entry passed to `misc_state.update_slides_catalog`. This allows building a reverse index `source_name → slug` at compile time.

Catalog entry shape after change:
```python
{
    "slug": slug,
    "title": entry["title"],
    "source_name": entry["source"].name,   # ← new
    "drive_export_url": entry["drive_export_url"],
    "group": entry.get("group"),
}
```

The reverse lookup is built on demand inside the compilation endpoint by scanning `misc_state.slides_catalog.values()`.

---

## Part 2: New Daemon Endpoint

**Route:** `GET /api/{session_id}/host/slides-compilation`  
**Router:** `daemon/misc/router.py :: host_router`  
**Auth:** host-only (inherits from `host_router` prefix, called directly on localhost:1234)  
**Response:** `StreamingResponse`, `application/pdf`, `Content-Disposition: attachment; filename="slides-compilation.pdf"`

### Algorithm

```
1. Build reverse index: source_name → {slug, drive_export_url}
   by scanning misc_state.slides_catalog.values()

2. Group slides_viewed by file_name:
   {file_name → set of page numbers (1-based)}

3. For each file_name, resolve slug + drive_export_url.
   Log a warning and skip if not found in catalog.

4. Parallel prefetch (asyncio.gather):
   For each slug NOT already cached on Railway
   (misc_state.slides_cache_status[slug].status != "cached"):
     - call download_on_railway(slug, drive_export_url)
     - as each Future completes, log progress:
       "[slides-compile] Downloaded N/TOTAL (XX%)"
   Already-cached slugs are counted as immediately done for progress.

5. For each slug (in file order):
   - fetch PDF bytes: GET /{session_id}/api/slides/download/{slug} via Railway
   - open with pypdf.PdfReader
   - for each viewed page number p (sorted):
     writer.add_page(reader.pages[p - 1])

6. Serialize writer to bytes buffer.
   Log "[slides-compile] Done — N pages from M decks"

7. Return StreamingResponse(bytes_buffer, media_type="application/pdf",
       headers={"Content-Disposition": 'attachment; filename="slides-compilation.pdf"'})
```

### Error handling
- Slug not in catalog → skip, warn
- Railway download failure for a slug → skip that deck, warn, continue with others
- No slides_viewed → return 204 No Content

### Dependency
Add `pypdf>=4.0` to `[project.optional-dependencies] daemon` in `pyproject.toml`.

---

## Part 3: Host UI

### Badge (`host.html`)
`#slides-log-badge`: add `onclick="toggleSlidesCompileConfirm()"`, change `cursor:default` → `cursor:pointer`.

### Confirm bubble (`host.html`)
Reuse the same inline-bubble pattern as the stop-session confirm bubble (already exists in the footer). Add a new `#slides-compile-confirm-bubble` positioned above the badge:

```
┌─────────────────────────────────────┐
│ Download viewed slides PDF?         │
│  [Download]                         │
└─────────────────────────────────────┘
```

The bubble contains:
- One-line label: "Download viewed slides PDF?"
- A single "Download" button that triggers the download and closes the bubble

No cancel button needed — clicking anywhere outside dismisses it (same as the existing stop-session bubble pattern).

### Download trigger (`host.js`)
```js
function triggerSlidesCompilationDownload() {
  closeSlidesCompileConfirm();
  window.location = '/api/' + _sessionId + '/host/slides-compilation';
}
```

`window.location` assignment triggers a file download without navigating away, since the response has `Content-Disposition: attachment`.

---

## What Is NOT Changing
- Participant page: no changes at all (LIVE badge already removed separately)
- Railway: no new endpoints, no new dependencies
- The existing slides-log hover popover behavior is preserved; clicking the badge just adds a confirm step on top

---

## Files to Touch
| File | Change |
|------|--------|
| `daemon/slides/loop.py` | Add `source_name` to catalog entries |
| `daemon/misc/router.py` | New `slides-compilation` host endpoint |
| `pyproject.toml` | Add `pypdf>=4.0` to daemon extras |
| `static/host.html` | Badge onclick + confirm bubble HTML |
| `static/host.js` | `toggleSlidesCompileConfirm` + `triggerSlidesCompilationDownload` |
