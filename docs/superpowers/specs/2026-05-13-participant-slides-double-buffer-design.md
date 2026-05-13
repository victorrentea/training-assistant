# Participant Slides — Double-Buffer Loading

**Date:** 2026-05-13
**Status:** Design — approved, pending implementation plan
**Scope:** Frontend only (`static/participant.html`); no backend changes

---

## Problem

When the active slide deck changes on the participant page, the current implementation clears the slide container and shows a centered blocking overlay ("Loading slides…") until the new PDF is fetched, rendered by pdf.js, and scrolled to the target page. The participant sees a blank screen for 1–5 seconds, depending on network and PDF size. This interrupts viewing in three scenarios:

1. **Host-follow new deck** — host moves to a different deck and the participant has follow enabled.
2. **Same-deck content refresh** — the trainer re-uploads the PPTX; `decks_updated` arrives with a new `downloaded_at` for the active slug.
3. **Manual topic switch** — the participant clicks a different topic in the sidebar.

Goal: never hide the slide the participant is looking at. Load the new PDF into an invisible buffer, render it, scroll it to the target page, and atomically reveal it only when fully ready.

## Non-goals

- Zoom (`pdfZoom`) is **not** double-buffered in this iteration. It currently re-renders the front buffer in place; the brief flicker on an explicit user action is acceptable.
- First-time slides view (no `pdfDoc` loaded yet) keeps the existing `#pdf-check-overlay` centered loader. Double-buffer only kicks in when there is already a visible slide.
- No backend changes. No protocol changes. No daemon changes.

## User-visible behavior

- The slide currently visible **never** disappears during a swap.
- A small badge appears top-left while a new PDF is being prefetched, reusing the existing `#slide-refresh-overlay` element. The badge is unobtrusive and does **not** cover the slide.
- When the new PDF is ready and scrolled to the correct page in the back buffer, the swap is atomic — one paint, no flicker.
- If the new PDF fails to load, the visible slide stays untouched and a discrete toast appears: "Slides nu s-au putut încărca. Reia când vrei." The user can retry by clicking the topic.

## Architecture

### DOM

Inside `#slides-view`, replace the single `#pdf-pages` container with a stack of two siblings:

```html
<div id="pdf-stack" class="relative flex-grow h-full">
  <div id="pdf-pages"     class="pdf-buffer buf-front">…</div>
  <div id="pdf-pages-buf" class="pdf-buffer buf-back">…</div>
</div>
```

CSS:

```css
.pdf-buffer { position: absolute; inset: 0; overflow-y: auto; }
.buf-front  { opacity: 1; pointer-events: auto; z-index: 2; }
.buf-back   { opacity: 0; pointer-events: none; z-index: 1; }
```

Both buffers are laid out in the same box, so `canvas.offsetWidth` is non-zero in the back buffer — the existing annotation `cssScale = canvas.offsetWidth / viewport.width` formula keeps working without refactor.

The swap is two `classList.replace` calls in the same JS task — atomic from the browser's paint perspective.

### State

Replace `let pdfDoc = null` with an explicit `Slides` object:

```js
const Slides = {
  front:    { el: pdfPagesEl,    pdfDoc: null, slug: null, dAt: null },
  back:     { el: pdfPagesBufEl, pdfDoc: null, slug: null, dAt: null },
  state:    'IDLE',      // 'IDLE' | 'PREFETCHING' | 'SWAPPING'
  abort:    null,        // AbortController for in-flight fetch
  loadTask: null,        // pdfjs loadingTask for destroy()
  wasAborted: false,     // suppresses toast on intentional cancel
};
```

`pdfDoc`-bound link-annotation handlers receive `localPdfDoc` as a closure parameter instead of referencing a module-level variable. This prevents stale handlers on old canvases from invoking `getDestination`/`getPageIndex` on the new pdfDoc after a swap.

The scroll listener stays attached to both buffers and reads from `Slides.front` only. Persistence to `localStorage` (`workshop_slide_page:<slug>`) uses `Slides.front.slug`.

### State machine

```
IDLE ──trigger──▶ PREFETCHING ──ready──▶ SWAPPING ──tick──▶ IDLE
  ▲                    │                                       │
  └─error/abort─────────┘                                       │
  └──────────────────────────────────────────────────────────────┘
```

Triggers that enter `PREFETCHING`:

| Trigger                              | Target slug       | Target page                            |
| ------------------------------------ | ----------------- | -------------------------------------- |
| host-follow → different deck         | new slug          | `_getHostCurrentPage(slidesCurrent)`   |
| `decks_updated` with new `dAt`       | same slug (active)| just-in-time read of front scroll page |
| user clicks a different topic        | new slug          | `localStorage` stored page or 1        |

Rule: **latest target wins.** If a new trigger arrives during `PREFETCHING`, the current prefetch is aborted (`AbortController` + `loadingTask.destroy()`), the back buffer DOM is cleared, and a new prefetch starts immediately. At most two `pdfDoc` instances exist at any moment (front visible + back in flight).

### Prefetch flow (`prefetchInto(target)`)

1. If `state === 'PREFETCHING'`: set `wasAborted = true`; abort + destroy in-flight task; `Slides.back.el.replaceChildren()`.
2. `state = 'PREFETCHING'`; show `#slide-refresh-overlay`.
3. Fetch PDF bytes through `PdfCache` (existing IndexedDB cache) or via `fetch(url, { signal: abort.signal })`; on success, persist to cache.
4. `pdfjsLib.getDocument({ data })` → `localPdfDoc`. Store `loadTask` on `Slides`.
5. `renderAllPagesInto(Slides.back, localPdfDoc, currentScale)` — same rendering code as today, parameterized on container and doc.
6. Resolve target page right before swap. For host-follow and manual click, this is fixed at trigger time. For the mtime same-deck case, re-read `_getCurrentSlidesPage()` on `Slides.front` so the participant's latest scroll position wins (they may have scrolled during the prefetch).
7. Synchronously set `Slides.back.el.scrollTop` to that page's section offset.
8. **Swap** (see below).
9. `state = 'IDLE'`; hide `#slide-refresh-overlay`.

### Swap

```js
function swap() {
  Slides.state = 'SWAPPING';
  Slides.front.el.classList.replace('buf-front', 'buf-back');
  Slides.back .el.classList.replace('buf-back',  'buf-front');
  [Slides.front, Slides.back] = [Slides.back, Slides.front];
  if (Slides.back.pdfDoc) { Slides.back.pdfDoc.destroy(); Slides.back.pdfDoc = null; }
  Slides.back.el.replaceChildren();
  Slides.state = 'IDLE';
}
```

`totalPages` and any view-level state shift to read from `Slides.front.pdfDoc` rather than a module-level variable.

## Error handling

All `await` points in `prefetchInto` are wrapped in a single `try / catch`. The `catch` checks `Slides.wasAborted`: if true, the failure is from a newer trigger taking over — no toast, no state change (the newer trigger has already set its own state). Otherwise:

| Failure                              | Behavior                                                                          |
| ------------------------------------ | --------------------------------------------------------------------------------- |
| `fetch` rejects (network / 404)      | Front buffer untouched. Toast via existing `showToast(...)`: "Slides nu s-au putut încărca. Reia când vrei." |
| `getDocument` rejects (corrupt)      | Same as above.                                                                    |
| `render` rejects                     | Same as above.                                                                    |
| `state === 'SWAPPING'` re-entrance   | Queue with `queueMicrotask` — guaranteed completion in next microtask.            |

On any caught error (non-aborted): hide `#slide-refresh-overlay`, clear `Slides.back.el`, dispose `loadTask`, set `state = 'IDLE'`. No automatic retries. No timeout — browser default `fetch` timeout (~30s) is sufficient; the badge stays visible to signal "still working." User can always click the topic to re-trigger.

## Edge cases

- **First-time slides view, no front `pdfDoc`:** keep the existing `#pdf-check-overlay` centered loader. Render directly into `Slides.front.el` and, on success, set `Slides.front.pdfDoc`, `Slides.front.slug`, `Slides.front.dAt`. Double-buffer only activates on subsequent triggers once `Slides.front.pdfDoc` is non-null.
- **User on non-slides view (notes/summary) during host change:** `_applyHostSlideFollow` exits early (already true today). No prefetch starts. When the user returns to slides view, the existing reconciliation logic triggers a prefetch — front buffer still shows the previous slide instantly.
- **Session reload (`reload` / `redirect` WS):** abort + destroy both buffers' pdfDocs before navigating.
- **Same-deck mtime case, user scrolling during prefetch:** target page is read **just before swap**, not at prefetch start. The user's latest scroll wins.
- **Annotation link clicks across a swap:** handlers capture `localPdfDoc` in closure; clicks on link annotations in the old buffer (which is now hidden, `pointer-events: none`) cannot happen anyway.

## Performance & memory

- Worst case: two `pdfDoc` instances in memory during prefetch. Each disposes via `destroy()` after the swap, freeing the pdfjs worker buffers and rendered page caches.
- Two `<canvas>` trees in DOM during prefetch. After swap, the back buffer is emptied with `replaceChildren()`.
- No additional listeners attached or removed across swaps — listeners on both buffers from init.
- IndexedDB `PdfCache` is unchanged; cache invalidation on `downloaded_at` change happens **before** prefetch.

## Testing

No automated tests — UX is timing- and visually-dependent. Manual verification in production (no participants connected during testing window):

1. **Topic switch (click):** load deck A, scroll to page 5, click deck B. Verify: deck A stays visible + badge top-left appears, then swap to deck B page 1. Zero blank screen.
2. **Host-follow new deck:** participant with follow on, viewing deck A. Host moves to deck B page 7. Verify: deck A visible + badge, swap to deck B page 7.
3. **Mtime refresh same deck:** participant on deck A page 5. Re-upload the PPTX. Verify: stays on page 5 across swap (just-in-time). Re-test while actively scrolling — the latest scroll position wins.
4. **Latest-wins race:** rapidly click deck A → B → C in <1s. Verify: final visible is C; no A→B→C parade.
5. **Failure path:** simulate 404 by mutating the URL in DevTools. Verify: front stays, toast appears, badge clears, click retry works.
6. **Memory:** DevTools Performance/Memory tab. Perform 20 deck switches. Verify: heap stable, no `pdfDoc` leak.

Each test produces a screenshot saved to `docs/superpowers/specs/screenshots/` as proof of completion.

## Files touched

- `static/participant.html` — DOM stack, CSS for buffers, `Slides` state object, `prefetchInto`, `swap`, refactor `renderAllPages` → `renderAllPagesInto(buffer, pdfDoc, scale)`, refactor `loadPdf` to dispatch first-time vs. prefetch path, update `selectTopic`, `_applyHostSlideFollow`, `decks_updated` handler.

That's the entire surface area. Estimated diff size: ~150 lines added / ~50 lines modified.

## Out of scope (future work)

- Double-buffered zoom.
- Pre-warming: prefetching the host's currently-pinned deck on participant connect, before any explicit trigger. Out of scope; would benefit cold loads.
- Telemetry: log swap timing histograms (prefetch duration, render duration) to OTel. Out of scope.
