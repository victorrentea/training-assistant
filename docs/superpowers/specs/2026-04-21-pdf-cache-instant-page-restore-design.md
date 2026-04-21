# PDF Browser Cache + Instant Page Restore — Design

**Date:** 2026-04-21  
**Status:** Approved, pending implementation

---

## Problem

1. **PDF re-download on every load.** Participants re-download the full PDF from Railway each time they switch to a slide deck — even within the same session or after a browser refresh. `cache: 'no-store'` is set on requests, defeating the browser cache entirely.

2. **Scroll-to-page artifact.** After loading a deck, PDF.js renders all pages starting from page 1, then a `setTimeout` (300–350 ms) fires to scroll to the target page. Participants briefly see page 1 before the scroll animation completes — jarring, especially mid-session when following the host.

---

## Goals

- PDF bytes are cached in the browser, persisting across deck switches and browser restarts.
- Cache is invalidated whenever the daemon re-downloads a PDF (PPTX update), for both online and reconnecting participants.
- When a deck loads, the participant immediately sees the correct page — no scroll animation, no flash of page 1.

---

## Design

### 1. `PdfCache` — IndexedDB module

A new JS object added to `participant.html`.

- **Storage:** IndexedDB, database `workshop-pdf-cache`, object store `pdfs`, key path `slug`
- **Value shape:** `{ slug: string, downloaded_at: string, data: ArrayBuffer }`

**API:**

```js
PdfCache.get(slug, expectedDownloadedAt)  // → ArrayBuffer | null
PdfCache.put(slug, downloaded_at, buffer) // → void
PdfCache.invalidate(slug)                 // → void
```

`get` returns `null` if the entry is missing or if `entry.downloaded_at !== expectedDownloadedAt` (stale).

---

### 2. `loadPdf(url, slug, downloadedAt, targetPage)` — enhanced signature

Old: `loadPdf(url)`  
New: `loadPdf(url, slug, downloadedAt, targetPage)`

**Execution sequence:**

1. Show `#pdf-loading-overlay` (covers `#pdf-pages`)
2. Call `PdfCache.get(slug, downloadedAt)`:
   - **HIT** → use cached `ArrayBuffer`, no network request
   - **MISS** → `fetch(url)` → `.arrayBuffer()` → `PdfCache.put(slug, downloadedAt, buffer)`
3. `pdfjsLib.getDocument({ data: buffer })` — bytes passed directly, not a URL
4. `renderAllPages(currentScale)`
5. Set `scrollTop` directly to target page's `offsetTop` — synchronous assignment, guarantees position is set before overlay is removed. **Do not use `scrollIntoView`** here; smooth-scroll is async and the overlay would hide before the position settles.
6. Hide `#pdf-loading-overlay` — participant sees correct page immediately

> Note: the existing `_scrollSlidesToPage()` (used for same-deck follow-mode jumps, where no overlay is involved) keeps its smooth-scroll behavior — that case is fine with animation.

**`targetPage` sources by caller:**

| Caller | targetPage |
|---|---|
| `selectTopic()` — manual deck select | `localStorage.getItem('workshop_slide_page:' + slug) \|\| 1` |
| `_applyHostSlideFollow()` — follow, deck switch | `_hostSlidesCurrent.page` |
| `DecksUpdatedMsg` handler — active deck re-downloaded | `_getCurrentSlidesPage()` (stay on current page) |

---

### 3. Cache invalidation

Two paths ensure participants always get the current PDF after a PPTX update:

**Path A — Online participant (WS-driven):**
1. Daemon re-downloads PDF → broadcasts `DecksUpdatedMsg` with new `downloaded_at`
2. Participant JS detects changed `downloaded_at` for slug → calls `PdfCache.invalidate(slug)`
3. Next `loadPdf()` call → cache miss → re-fetches fresh PDF from Railway

**Path B — Reconnecting participant (missed WS):**
1. On reconnect, `/api/participant/state` returns updated `downloaded_at` for all decks
2. `_slidesCacheStatus` is refreshed with new `downloaded_at`
3. `loadPdf()` calls `PdfCache.get(slug, newDownloadedAt)` → mismatch with stored entry → returns `null`
4. Re-fetches fresh PDF without any explicit invalidation call

Both paths guarantee the new PDF is delivered. Path B is an implicit safety net requiring no extra code beyond the `downloaded_at` comparison already in `get()`.

---

### 4. Loading overlay

New element added inside the slides panel, sibling of `#pdf-pages`:

```html
<div id="pdf-loading-overlay">Loading slides…</div>
```

- Positioned absolutely to cover `#pdf-pages`
- Shown at the start of `loadPdf()`, hidden after scroll is set and before the overlay is removed
- Styled consistently with existing UI (neutral background, small spinner or text)

---

### 5. Artifacts removed

The following are deleted as part of this change:

- `document.getElementById('pdf-pages').scrollTop = 0` in `loadPdf()`
- `setTimeout(() => _scrollSlidesToPage(storedPage), 300)` in `selectTopic()`
- `setTimeout(() => _scrollSlidesToPage(targetPage), 350)` in `_applyHostSlideFollow()`
- `url + '?v=' + Date.now()` cache-buster in `DecksUpdatedMsg` handler (replaced by `PdfCache.invalidate()`)

---

## Sequence Diagram

See [`docs/sequences/pdf-cache-page-restore.puml`](../sequences/pdf-cache-page-restore.puml).

---

## Out of Scope

- Lazy / priority rendering of only the target page (Option B from brainstorming) — not needed once the overlay hides the render phase
- HTTP ETag approach — IndexedDB gives explicit invalidation control; ETag would require a network round-trip on every load
- Storage quota management — browser IndexedDB quotas are large enough for typical workshop PDF sizes; eviction can be added later if needed
