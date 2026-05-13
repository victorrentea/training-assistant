# Participant Slides Double-Buffer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-buffer slide loader on the participant page with a twin-container double-buffer so the visible slide never disappears during deck switches, mtime refreshes, or host-follow changes.

**Architecture:** Two sibling `<div>` buffers stacked with `position:absolute; inset:0` inside `#pdf-stack`. The "front" buffer is visible; the "back" buffer prefetches the new PDF, renders all pages with pdf.js, and scrolls to the target page. A CSS class swap (`buf-front` ↔ `buf-back`) flips visibility atomically in one paint. State lives in a single `Slides` object; the `prefetchInto(target)` coroutine implements latest-wins via `AbortController` + `loadingTask.destroy()`. All-front-buffer first-time load keeps the existing `#pdf-check-overlay` blocking path.

**Tech Stack:** Vanilla JS + pdf.js 5.4.149 (already on CDN), Tailwind utility classes (already loaded), IndexedDB `PdfCache` (existing). No build step. No new dependencies. All changes in one file: `static/participant.html`.

**Reference spec:** [`docs/superpowers/specs/2026-05-13-participant-slides-double-buffer-design.md`](../specs/2026-05-13-participant-slides-double-buffer-design.md)

---

## Deployment & Verification Loop

Per CLAUDE.md, every commit pushed to `master` auto-deploys to Railway in ~40-50s. There are **no automated tests** for this feature — UX is timing- and visually-dependent and tied to pdf.js rendering. After each task that pushes, use `superpowers:wait-for-deploy` (or wait ~60s then probe `static/version.js` for the new commit hash) and then manually verify in production at `$WORKSHOP_SERVER_URL`.

**Manual verification window:** the user confirmed nobody is connected to production during implementation, so prod is a safe test bed.

**Standard manual smoke check after every push:**
1. Open `$WORKSHOP_SERVER_URL/<session>` as a participant.
2. Click into Slides tab → pick a deck → verify it loads normally (no regressions).
3. Open browser DevTools console → confirm no errors during slide loading or WS messages.

Capture a screenshot only on tasks marked **[VERIFY]** below; store at `docs/superpowers/specs/screenshots/dbuf-task-N-<scenario>.png`.

---

## File Structure

All changes touch **one file**: `static/participant.html`.

Logical regions inside the file (line numbers from current HEAD):

| Region                                  | Current lines  | Touched by tasks |
| --------------------------------------- | -------------- | ---------------- |
| Slides view DOM (`#slides-view`)        | 461–482        | Task 1           |
| `PdfCache` IIFE                         | 522–584        | (unchanged)      |
| pdf.js module (`renderAllPages`, etc.)  | 586–724        | Tasks 2, 3, 4, 5, 9 |
| `_scrollSlidesToPage`, `_getCurrentSlidesPage`, helpers | 889–905 | Task 3 |
| `selectTopic` (manual click)            | 1576–1616      | Task 6           |
| `_applyHostSlideFollow` / `_onIncomingHostSlidesCurrent` | 937–979 | Task 8 |
| `decks_updated` WS handler              | 2515–2575      | Task 7           |

No new files. No new dependencies.

---

## Task 1: DOM stack + CSS for buffers (no behavior change)

Adds the second buffer to the DOM and CSS to make it invisible. The first buffer keeps its `id="pdf-pages"` so all existing JS continues to work unchanged. After this task, slides still load and render exactly as today — the back buffer is just an empty hidden sibling.

**Files:**
- Modify: `static/participant.html:461-482` (slides view DOM)
- Modify: `static/participant.html:~16` (extend `<style>` block — find existing `#past-slides-badge` rule and add new rules nearby)

- [ ] **Step 1.1: Add `#pdf-stack` wrapper + `#pdf-pages-buf` sibling**

Replace the existing block at `static/participant.html:478-481`:

```html
<!-- Slides Container -->
<div id="pdf-pages" class="flex-grow overflow-y-auto scroll-smooth py-8 px-8 space-y-4 h-full"></div>
<!-- Hidden page info element updated by JS — read by tests -->
<span id="pdf-page-info" hidden></span>
```

With:

```html
<!-- Slides Container (double-buffer stack) -->
<div id="pdf-stack" class="flex-grow relative h-full">
  <div id="pdf-pages"     class="pdf-buffer buf-front overflow-y-auto scroll-smooth py-8 px-8 space-y-4"></div>
  <div id="pdf-pages-buf" class="pdf-buffer buf-back  overflow-y-auto scroll-smooth py-8 px-8 space-y-4" aria-hidden="true"></div>
</div>
<!-- Hidden page info element updated by JS — read by tests -->
<span id="pdf-page-info" hidden></span>
```

Note: `flex-grow` moved to the new `#pdf-stack`; `h-full` removed from buffers because `inset:0` will size them.

- [ ] **Step 1.2: Add CSS for the buffer stack**

Find the `<style>` block near the top of `static/participant.html` (line ~16). After the existing `#past-slides-badge` rule, append:

```css
.pdf-buffer { position: absolute; inset: 0; }
.buf-front  { opacity: 1; pointer-events: auto; z-index: 2; }
.buf-back   { opacity: 0; pointer-events: none; z-index: 1; }
```

- [ ] **Step 1.3: Commit and push**

```bash
git add static/participant.html
git commit -m "feat(slides): stack DOM for double-buffer (no behavior change)

Adds #pdf-stack wrapper and #pdf-pages-buf hidden sibling. Front buffer
keeps id=pdf-pages so all existing JS continues to read/write through
it unchanged. Back buffer is invisible (opacity:0, pointer-events:none)
but laid out so canvas.offsetWidth is non-zero — required for annotation
cssScale to work when we start rendering into it.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push origin master
```

- [ ] **Step 1.4: Wait for deploy** (use `superpowers:wait-for-deploy` skill or wait 60s and probe `static/version.js`)

- [ ] **Step 1.5: [VERIFY] manual smoke check in prod**

Open `$WORKSHOP_SERVER_URL/<active-session>` as a participant. Navigate to Slides tab and select a deck. Confirm:
- Slides render normally, no visual regression.
- Scrolling works.
- DevTools Elements panel shows `#pdf-stack > #pdf-pages (visible) + #pdf-pages-buf (empty, opacity:0)`.
- No console errors.

Screenshot → `docs/superpowers/specs/screenshots/dbuf-task-1-stack.png`.

---

## Task 2: Refactor `renderAllPages` → `renderAllPagesInto(container, localPdfDoc, scale)`

Pure refactor. Pulls the container reference and pdfDoc out of the closure into explicit parameters. Link-annotation `getDestination`/`getPageIndex` handlers now capture `localPdfDoc` — critical for the upcoming swap, where the old buffer's handlers must not reference the new doc.

**Files:**
- Modify: `static/participant.html:594-664` (`renderAllPages`)
- Modify: `static/participant.html:692-696` (`pdfZoom` caller)
- Modify: `static/participant.html:698-723` (`loadPdf` caller)

- [ ] **Step 2.1: Replace `renderAllPages` with `renderAllPagesInto`**

Replace lines 594-664 with:

```js
  async function renderAllPagesInto(container, localPdfDoc, scale) {
    container.replaceChildren();
    const numPages = localPdfDoc.numPages;
    for (let i = 1; i <= numPages; i++) {
      const page = await localPdfDoc.getPage(i);
      const viewport = page.getViewport({ scale });
      const section = document.createElement('section');
      section.className = 'relative group';
      section.dataset.page = i;
      const canvas = document.createElement('canvas');
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      canvas.className = 'w-full whisper-shadow rounded-2xl';
      section.appendChild(canvas);
      if (i === numPages) section.classList.add('pb-32');
      container.appendChild(section);
      await page.render({ canvasContext: canvas.getContext('2d'), viewport }).promise;
      const annotations = await page.getAnnotations({ intent: 'display' });
      if (annotations && annotations.length) {
        const annLayer = document.createElement('div');
        const cssScale = canvas.offsetWidth / viewport.width;
        annLayer.style.cssText = `position:absolute;left:0;top:0;width:${viewport.width}px;height:${viewport.height}px;pointer-events:none;transform:scale(${cssScale});transform-origin:top left;`;
        section.appendChild(annLayer);
        for (const ann of annotations) {
          if (!ann || ann.subtype !== 'Link' || !Array.isArray(ann.rect)) continue;
          const rect = viewport.convertToViewportRectangle(ann.rect);
          const left = Math.min(rect[0], rect[2]);
          const top = Math.min(rect[1], rect[3]);
          const width = Math.abs(rect[0] - rect[2]);
          const height = Math.abs(rect[1] - rect[3]);
          if (!(width > 0 && height > 0)) continue;
          const link = document.createElement('a');
          link.style.cssText = [
            'position:absolute',
            `left:${left}px`,
            `top:${top}px`,
            `width:${width}px`,
            `height:${height}px`,
            'pointer-events:auto',
            'cursor:pointer',
            'background:transparent'
          ].join(';');
          if (ann.url || ann.unsafeUrl) {
            link.href = ann.url || ann.unsafeUrl;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
          } else if (ann.dest) {
            link.href = '#';
            link.addEventListener('click', async (ev) => {
              ev.preventDefault();
              try {
                const dest = Array.isArray(ann.dest) ? ann.dest : await localPdfDoc.getDestination(ann.dest);
                if (!dest || !dest[0]) return;
                const pageRef = dest[0];
                const pageIndex = await localPdfDoc.getPageIndex(pageRef);
                const targetPage = pageIndex + 1;
                const targetSection = container.querySelector(`section[data-page="${targetPage}"]`);
                if (targetSection) targetSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
              } catch (_) {
                // Ignore malformed destinations.
              }
            });
          } else {
            continue;
          }
          annLayer.appendChild(link);
        }
      }
    }
    updatePageInfo();
  }
```

Key changes vs. original:
- `container` and `localPdfDoc` are parameters (was: read from outer closure).
- `numPages` derived from `localPdfDoc.numPages` (was: outer `totalPages`).
- Annotation `getDestination` and `getPageIndex` use `localPdfDoc` (was: outer `pdfDoc`).
- `container.replaceChildren()` instead of `container.innerHTML = ''` (slightly more idiomatic, equivalent effect).

- [ ] **Step 2.2: Update `pdfZoom` to use new signature**

Replace lines 692-696 with:

```js
  window.pdfZoom = async function(delta) {
    if (!pdfDoc) return;
    currentScale = Math.max(0.5, Math.min(3, currentScale + delta));
    await renderAllPagesInto(document.getElementById('pdf-pages'), pdfDoc, currentScale);
  };
```

- [ ] **Step 2.3: Update `loadPdf` to use new signature**

In the body of `loadPdf` (lines 698-723), find:

```js
      pdfDoc = await pdfjsLib.getDocument({ data: new Uint8Array(buffer) }).promise;
      totalPages = pdfDoc.numPages;
      await renderAllPages(currentScale);
```

Replace with:

```js
      pdfDoc = await pdfjsLib.getDocument({ data: new Uint8Array(buffer) }).promise;
      totalPages = pdfDoc.numPages;
      await renderAllPagesInto(document.getElementById('pdf-pages'), pdfDoc, currentScale);
```

- [ ] **Step 2.4: Commit and push**

```bash
git add static/participant.html
git commit -m "refactor(slides): parameterize renderAllPagesInto(container, pdfDoc, scale)

Pure refactor. Container and pdfDoc are now explicit parameters instead
of read from closure. Annotation getDestination/getPageIndex handlers
capture localPdfDoc — required so swap doesn't leave stale handlers
referencing the wrong doc.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push origin master
```

- [ ] **Step 2.5: Wait for deploy + manual smoke check**

Same as Task 1.5. Confirm slides load, scroll, click links work, zoom (if exposed) works. No new behavior expected.

---

## Task 3: Introduce `Slides` state object

Replace the closure-scoped `pdfDoc`, `totalPages`, and direct `document.getElementById('pdf-pages')` calls with a single `Slides` object. `Slides.front` is the visible buffer; `Slides.back` is the prefetch target (still unused after this task). All reads go through `Slides.front`. After this task, behavior is unchanged but the state shape is ready for prefetch.

**Files:**
- Modify: `static/participant.html:586-724` (pdf.js module — top of script)
- Modify: `static/participant.html:889-896` (`_scrollSlidesToPage`)

- [ ] **Step 3.1: Replace `pdfDoc` / `totalPages` / `currentScale` declarations with `Slides` object**

In the `<script type="module">` block starting at line 586, replace lines 590-592:

```js
  let pdfDoc = null;
  let currentScale = 1.5;
  let totalPages = 0;
```

With:

```js
  const Slides = {
    front: { el: null, pdfDoc: null, slug: null, dAt: null },
    back:  { el: null, pdfDoc: null, slug: null, dAt: null },
    scale: 1.5,
    state: 'IDLE',       // 'IDLE' | 'PREFETCHING' | 'SWAPPING'
    abort: null,
    loadTask: null,
    wasAborted: false,
  };
  // Back-compat shims for code paths that still reference module-level names.
  // Removed in later tasks once all references are migrated.
  let pdfDoc = null;
  let currentScale = 1.5;
  let totalPages = 0;
  window.Slides = Slides; // exposed so non-module script (triggers) can read state
```

(The shims `pdfDoc`/`currentScale`/`totalPages` keep `pdfZoom`, `loadPdf`, and `updatePageInfo` working until we migrate them in Step 3.4.)

- [ ] **Step 3.2: Initialize `Slides.front.el` and `Slides.back.el` in `init()`**

Find the `(function init() { ... })()` block at lines 680-690. Replace it with:

```js
  (function init() {
    Slides.front.el = document.getElementById('pdf-pages');
    Slides.back.el  = document.getElementById('pdf-pages-buf');
    function onScroll() {
      if (this !== Slides.front.el) return;
      updatePageInfo();
      var page = _getCurrentSlidesPage();
      // Persist using Slides.front.slug (currently visible deck), NOT _activeSlideSlug
      // (which is updated immediately on click, before swap — would mis-attribute scroll
      // position to the new deck while the old one is still visible).
      var visibleSlug = Slides.front.slug;
      if (page && visibleSlug) {
        localStorage.setItem('workshop_slide_page:' + visibleSlug, page);
      }
    }
    Slides.front.el.addEventListener('scroll', onScroll);
    Slides.back.el .addEventListener('scroll', onScroll);
    const infoEl = document.getElementById('pdf-page-info');
    if (infoEl) infoEl.textContent = '— / —';
  })();
```

The listener is attached to both buffers but exits early unless the event fires on the current front. After a swap, the new front's listener naturally takes over.

- [ ] **Step 3.3: Update `updatePageInfo` to read from `Slides.front`**

Find `updatePageInfo()` at lines 666-678. Replace with:

```js
  function updatePageInfo() {
    const infoEl = document.getElementById('pdf-page-info');
    if (!infoEl) return;
    const container = Slides.front.el;
    const doc = Slides.front.pdfDoc;
    if (!container || !doc) { infoEl.textContent = '— / —'; return; }
    const sections = container.querySelectorAll('section[data-page]');
    const scrollTop = container.scrollTop;
    const midY = scrollTop + container.clientHeight / 2;
    let current = 1;
    sections.forEach(function(s) {
      if (s.offsetTop <= midY) current = parseInt(s.dataset.page);
    });
    infoEl.textContent = current + ' / ' + doc.numPages;
  }
```

- [ ] **Step 3.4: Migrate `pdfZoom` and `loadPdf` to write through `Slides.front`**

Replace `pdfZoom` (lines 692-696, post Task 2):

```js
  window.pdfZoom = async function(delta) {
    if (!Slides.front.pdfDoc) return;
    Slides.scale = Math.max(0.5, Math.min(3, Slides.scale + delta));
    await renderAllPagesInto(Slides.front.el, Slides.front.pdfDoc, Slides.scale);
  };
```

Replace `loadPdf` (lines 698-723, post Task 2):

```js
  window.loadPdf = async function(url, slug, downloadedAt, targetPage) {
    var overlay = document.getElementById('pdf-check-overlay');
    if (overlay) overlay.style.display = 'flex';
    try {
      var buffer = slug ? await PdfCache.get(slug, downloadedAt) : null;
      if (!buffer) {
        var resp = await fetch(url);
        if (!resp.ok) throw new Error('PDF fetch failed: ' + resp.status);
        buffer = await resp.arrayBuffer();
        if (slug && downloadedAt) await PdfCache.put(slug, downloadedAt, buffer);
      }
      const newDoc = await pdfjsLib.getDocument({ data: new Uint8Array(buffer) }).promise;
      // Dispose previous front doc if any (first-time path replaces).
      if (Slides.front.pdfDoc) Slides.front.pdfDoc.destroy();
      Slides.front.pdfDoc = newDoc;
      Slides.front.slug = slug || null;
      Slides.front.dAt  = downloadedAt || null;
      await renderAllPagesInto(Slides.front.el, newDoc, Slides.scale);
      var page = (targetPage && targetPage > 1) ? targetPage : 1;
      if (page > 1) {
        var section = Slides.front.el.querySelector('section[data-page="' + page + '"]');
        if (section) section.scrollIntoView({ behavior: 'instant', block: 'start' });
      }
    } catch(e) {
      console.error('PDF load error', e);
    } finally {
      if (overlay) overlay.style.display = 'none';
    }
  };
```

- [ ] **Step 3.5: Remove the back-compat shims**

In Step 3.1 we kept `pdfDoc`/`currentScale`/`totalPages` shims. After Steps 3.3 and 3.4, no code reads them anymore. Verify with grep, then delete them.

```bash
grep -n -w "pdfDoc\|currentScale\|totalPages" static/participant.html | grep -v "Slides\." | grep -v "localPdfDoc\|newDoc\|pdfDocument"
```

Expected: empty (or only comments). If any references remain, fix them first, then delete the three `let` lines added in Step 3.1.

Delete these three lines:

```js
  let pdfDoc = null;
  let currentScale = 1.5;
  let totalPages = 0;
```

- [ ] **Step 3.6: Update `_scrollSlidesToPage` to read from `Slides.front.el`**

In the non-module script block, find `_scrollSlidesToPage` at lines 889-896:

```js
function _scrollSlidesToPage(page) {
  var targetPage = Math.max(1, Number(page || 1));
  var container = document.getElementById('pdf-pages');
  if (!container) return false;
  var section = container.querySelector('section[data-page="' + targetPage + '"]');
  if (!section) return false;
  section.scrollIntoView({ behavior: 'smooth', block: 'start' });
  return true;
}
```

Replace with:

```js
function _scrollSlidesToPage(page) {
  var targetPage = Math.max(1, Number(page || 1));
  var container = (window.Slides && window.Slides.front && window.Slides.front.el)
    ? window.Slides.front.el
    : document.getElementById('pdf-pages');
  if (!container) return false;
  var section = container.querySelector('section[data-page="' + targetPage + '"]');
  if (!section) return false;
  section.scrollIntoView({ behavior: 'smooth', block: 'start' });
  return true;
}
```

(The fallback to `getElementById` covers the case where `Slides` is not yet initialized — defensive.)

- [ ] **Step 3.7: Commit and push**

```bash
git add static/participant.html
git commit -m "refactor(slides): introduce Slides state object (front/back buffers)

Replaces module-level pdfDoc/totalPages/currentScale with a single
Slides object. Slides.front is the only buffer used after this commit;
Slides.back is initialized but unused. Scroll listeners attach to both
buffers but only act on the current front. Behavior unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push origin master
```

- [ ] **Step 3.8: Wait for deploy + manual smoke check**

Same as before. Additionally in DevTools console verify:
```js
window.Slides.front.pdfDoc  // -> non-null after a slide loads
window.Slides.back.pdfDoc   // -> null
window.Slides.state          // -> 'IDLE'
```

---

## Task 4: Implement `swap()` (dormant)

Adds the swap function to the pdf.js module. Not called from anywhere yet — purely additive.

**Files:**
- Modify: `static/participant.html` — pdf.js module, add after `renderAllPagesInto`

- [ ] **Step 4.1: Add `swap()` function**

Inside the `<script type="module">` block, after `renderAllPagesInto`'s closing brace and before `updatePageInfo`, add:

```js
  function swap() {
    if (Slides.state === 'SWAPPING') return; // re-entrance guard
    Slides.state = 'SWAPPING';
    // Flip classes atomically — one paint
    Slides.front.el.classList.replace('buf-front', 'buf-back');
    Slides.back .el.classList.replace('buf-back',  'buf-front');
    // Swap references so Slides.front always points at the visible buffer
    const oldFront = Slides.front;
    Slides.front = Slides.back;
    Slides.back  = oldFront;
    // Dispose the now-hidden previous doc and empty its DOM
    if (Slides.back.pdfDoc) {
      try { Slides.back.pdfDoc.destroy(); } catch (_) {}
      Slides.back.pdfDoc = null;
    }
    Slides.back.slug = null;
    Slides.back.dAt  = null;
    Slides.back.el.replaceChildren();
    Slides.state = 'IDLE';
    updatePageInfo();
  }
```

- [ ] **Step 4.2: Commit and push**

```bash
git add static/participant.html
git commit -m "feat(slides): add dormant swap() function for double-buffer

Adds the atomic buffer-swap function. Not called yet. Flips CSS classes
on both buffers in the same JS task (browser paints once, zero flicker),
swaps Slides.front/Slides.back references, disposes the previous pdfDoc.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push origin master
```

- [ ] **Step 4.3: Wait for deploy + manual smoke check** (same as before).

---

## Task 5: Implement `prefetchInto(target)` (dormant)

Adds the prefetch coroutine. Not called from anywhere yet — purely additive.

**Files:**
- Modify: `static/participant.html` — pdf.js module, add after `swap`

- [ ] **Step 5.1: Add `prefetchInto` function**

Inside the `<script type="module">` block, after `swap`, add:

```js
  /**
   * target = { url, slug, downloadedAt, getPage }
   *   getPage: () => number  — resolved just before swap, so the
   *   participant's latest scroll (mtime case) wins.
   */
  async function prefetchInto(target) {
    // If a prefetch is in flight, cancel it.
    if (Slides.state === 'PREFETCHING') {
      Slides.wasAborted = true;
      if (Slides.abort) { try { Slides.abort.abort(); } catch (_) {} }
      if (Slides.loadTask) { try { Slides.loadTask.destroy(); } catch (_) {} }
      Slides.back.el.replaceChildren();
      if (Slides.back.pdfDoc) {
        try { Slides.back.pdfDoc.destroy(); } catch (_) {}
        Slides.back.pdfDoc = null;
      }
    }
    if (Slides.state === 'SWAPPING') {
      // Defer to next microtask — swap completes synchronously
      await Promise.resolve();
    }

    Slides.state = 'PREFETCHING';
    Slides.wasAborted = false;
    Slides.abort = new AbortController();
    var overlay = document.getElementById('slide-refresh-overlay');
    if (overlay) overlay.style.display = '';

    try {
      // 1. Fetch bytes (IndexedDB cache first, then network)
      let buffer = target.slug
        ? await PdfCache.get(target.slug, target.downloadedAt)
        : null;
      if (!buffer) {
        const resp = await fetch(target.url, { signal: Slides.abort.signal });
        if (!resp.ok) throw new Error('PDF fetch failed: ' + resp.status);
        buffer = await resp.arrayBuffer();
        if (target.slug && target.downloadedAt) {
          await PdfCache.put(target.slug, target.downloadedAt, buffer);
        }
      }

      // 2. Parse PDF
      const loadingTask = pdfjsLib.getDocument({ data: new Uint8Array(buffer) });
      Slides.loadTask = loadingTask;
      const localPdfDoc = await loadingTask.promise;

      // 3. Render into back buffer
      Slides.back.pdfDoc = localPdfDoc;
      Slides.back.slug   = target.slug || null;
      Slides.back.dAt    = target.downloadedAt || null;
      await renderAllPagesInto(Slides.back.el, localPdfDoc, Slides.scale);

      // 4. Resolve target page just before swap
      const targetPage = Math.max(1, Number((target.getPage && target.getPage()) || 1));
      const section = Slides.back.el.querySelector('section[data-page="' + targetPage + '"]');
      if (section) {
        // Use scrollTop = section.offsetTop directly (no animation, instant) so the
        // user sees the right page on the first paint after swap.
        Slides.back.el.scrollTop = section.offsetTop;
      } else {
        Slides.back.el.scrollTop = 0;
      }

      // 5. Atomic swap
      swap();

    } catch (e) {
      if (Slides.wasAborted || (e && e.name === 'AbortError')) {
        // Newer trigger took over — silent.
        return;
      }
      console.error('Slides prefetch error', e);
      // Front buffer untouched; clean up back.
      try { if (Slides.back.pdfDoc) Slides.back.pdfDoc.destroy(); } catch (_) {}
      Slides.back.pdfDoc = null;
      Slides.back.el.replaceChildren();
      if (typeof window.showToast === 'function') {
        window.showToast('Slides nu s-au putut încărca. Reia când vrei.');
      }
    } finally {
      if (!Slides.wasAborted) {
        Slides.state = 'IDLE';
        if (overlay) overlay.style.display = 'none';
      }
      Slides.abort = null;
      Slides.loadTask = null;
    }
  }
  window.prefetchInto = prefetchInto;  // expose for triggers in non-module script
```

Note: `showToast` is defined in the non-module script block — accessible via `window.showToast`. The export at the bottom (`window.prefetchInto`) lets the non-module triggers call it.

- [ ] **Step 5.2: Commit and push**

```bash
git add static/participant.html
git commit -m "feat(slides): add dormant prefetchInto() coroutine

Implements the full prefetch flow: cancel any in-flight prefetch (latest
wins), fetch via PdfCache + AbortController, parse, render into back
buffer, JIT scroll to target page, then swap(). On error: toast 'Slides
nu s-au putut încărca'. On abort (newer trigger): silent.

Exposed as window.prefetchInto so the non-module triggers can call it
in later tasks. Not wired to any trigger yet.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push origin master
```

- [ ] **Step 5.3: Wait for deploy + manual smoke check** + DevTools verify `window.prefetchInto` is a function.

---

## Task 6: Wire trigger — manual topic click [VERIFY]

`selectTopic` is called when the user clicks a topic in the sidebar. After this task, clicking a different topic while a slide is already visible uses double-buffer.

**Files:**
- Modify: `static/participant.html:1576-1616` (`selectTopic`)

- [ ] **Step 6.1: Refactor `selectTopic` to dispatch on `Slides.front.pdfDoc`**

Find `selectTopic` at line 1576. The current body (lines 1590-1614) is:

```js
  if (slide && slide.url && window.loadPdf) {
    if (slide.slug && _sessionId) {
      var _checkOverlay = document.getElementById('pdf-check-overlay');
      if (_checkOverlay) { _checkOverlay.style.display = 'flex'; }
      try {
        var checkUrl = '/' + _sessionId + '/api/slides/check/' + encodeURIComponent(slide.slug);
        var resp = await fetch(checkUrl, { cache: 'no-store', headers: { 'X-Participant-ID': _myUUID } });
        if (!resp.ok) throw new Error(resp.status);
      } catch(e) {
        if (_checkOverlay) { _checkOverlay.style.display = 'none'; }
        showToast('Slide not ready on server yet. Try again in a few seconds.');
        return;
      }
      // Do NOT hide overlay here — loadPdf will hide it after rendering
    }
    var dlUrl = slide.url + (slide.url.includes('?') ? '&' : '?') + 'download=1';
    var dlBtn = document.getElementById('pdf-download');
    if (dlBtn) { dlBtn.href = dlUrl; dlBtn.setAttribute('download', slide.name || ''); }
    var downloadedAt = (_slidesCacheStatus[slide.slug] || {}).downloaded_at || null;
    var storedPage = slide.slug ? parseInt(localStorage.getItem('workshop_slide_page:' + slide.slug) || '1', 10) : 1;
    var targetPage = targetPageOverride || (storedPage > 1 ? storedPage : 1);
    await window.loadPdf(slide.url, slide.slug, downloadedAt, targetPage);
    _activeSlideId = slide._id || null;
    _activeSlideSlug = slide.slug || null;
    if (_activeSlideSlug) LS.setActiveSlide(_activeSlideSlug);
  }
```

Replace with:

```js
  if (slide && slide.url) {
    if (slide.slug && _sessionId) {
      var hasFront = !!(window.Slides && window.Slides.front && window.Slides.front.pdfDoc);
      var _checkOverlay = document.getElementById('pdf-check-overlay');
      // Centered loader only on first-time (no visible slide yet).
      if (!hasFront && _checkOverlay) { _checkOverlay.style.display = 'flex'; }
      try {
        var checkUrl = '/' + _sessionId + '/api/slides/check/' + encodeURIComponent(slide.slug);
        var resp = await fetch(checkUrl, { cache: 'no-store', headers: { 'X-Participant-ID': _myUUID } });
        if (!resp.ok) throw new Error(resp.status);
      } catch(e) {
        if (!hasFront && _checkOverlay) { _checkOverlay.style.display = 'none'; }
        showToast('Slide not ready on server yet. Try again in a few seconds.');
        return;
      }
    }
    var dlUrl = slide.url + (slide.url.includes('?') ? '&' : '?') + 'download=1';
    var dlBtn = document.getElementById('pdf-download');
    if (dlBtn) { dlBtn.href = dlUrl; dlBtn.setAttribute('download', slide.name || ''); }
    var downloadedAt = (_slidesCacheStatus[slide.slug] || {}).downloaded_at || null;
    var storedPage = slide.slug ? parseInt(localStorage.getItem('workshop_slide_page:' + slide.slug) || '1', 10) : 1;
    var targetPage = targetPageOverride || (storedPage > 1 ? storedPage : 1);
    _activeSlideId = slide._id || null;
    _activeSlideSlug = slide.slug || null;
    if (_activeSlideSlug) LS.setActiveSlide(_activeSlideSlug);

    var frontReady = !!(window.Slides && window.Slides.front && window.Slides.front.pdfDoc);
    if (frontReady && window.prefetchInto) {
      // Double-buffer path: old slide stays visible, new loads in back.
      // We DO await so callers (_applyHostSlideFollow, _openSlideFromHistory)
      // that chain follow-up actions (like _scrollSlidesToPage) see the swap done.
      var capturedPage = targetPage;
      await window.prefetchInto({
        url: slide.url,
        slug: slide.slug,
        downloadedAt: downloadedAt,
        getPage: function() { return capturedPage; },
      });
    } else if (window.loadPdf) {
      // First-time path: centered overlay + render into front directly.
      await window.loadPdf(slide.url, slide.slug, downloadedAt, targetPage);
    }
  }
```

Key changes:
- `hasFront` decides whether to show the centered `#pdf-check-overlay` (only on first-time).
- After `_activeSlideSlug` is set, dispatch on `frontReady`: prefetch when visible slide exists; else fall through to existing `loadPdf`.
- `capturedPage` closes over `targetPage` for the JIT-page resolver. Click case: target is fixed at click time.

- [ ] **Step 6.2: Pass `targetPage` through `_openSlideFromHistory`**

History navigation (`_openSlideFromHistory`) currently calls `selectTopic(..., slide)` without the 4th `targetPageOverride` argument and relies on a trailing `_scrollSlidesToPage(targetPage)` to position. With double-buffer, the prefetched scroll happens INSIDE `prefetchInto`, so we must hand the page to `selectTopic`.

At `static/participant.html:914-917`, change:

```js
  if (!sameSlideAlreadyOpen) {
    await selectTopic(topicEl || document.querySelector('.topic-item'), null, slide);
  }
```

To:

```js
  if (!sameSlideAlreadyOpen) {
    await selectTopic(topicEl || document.querySelector('.topic-item'), null, slide, targetPage);
  }
```

(The trailing `_scrollSlidesToPage(targetPage)` calls after this become a no-op safety net once `await selectTopic` resolves — by then `Slides.front` is the new buffer already scrolled to `targetPage`.)

- [ ] **Step 6.3: Commit and push**

```bash
git add static/participant.html
git commit -m "feat(slides): wire manual topic click to double-buffer path

selectTopic now dispatches: first-time → existing loadPdf with centered
overlay; subsequent clicks → prefetchInto with old slide remaining
visible during background load. selectTopic awaits prefetchInto so
callers that chain follow-ups (history navigation) see the swap done.
_openSlideFromHistory now passes targetPage through to selectTopic so
the prefetched buffer is scrolled to the correct page before swap.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push origin master
```

- [ ] **Step 6.4: Wait for deploy.**

- [ ] **Step 6.5: [VERIFY] Manual test in prod — manual click**

1. Open `$WORKSHOP_SERVER_URL/<session>` as participant.
2. Navigate to Slides tab. Click deck A — verify centered "Loading slides…" overlay appears (first-time path). Wait for render.
3. Scroll deck A to page 5.
4. Click deck B in the sidebar.
5. **Expected:** deck A stays fully visible. Top-LEFT small spinner badge appears. After 1–3s, swap happens: deck B is now visible, scrolled to its stored page or page 1. Zero blank screen.
6. Click deck A again. Same behavior: deck B stays visible, badge top-left, then atomic swap to deck A at page 5 (stored page).
7. DevTools console: no errors. `window.Slides.front.slug` matches the visible deck.
8. **History navigation:** open the past-slides panel, click a historic entry that targets a different deck + non-1 page. Verify the participant lands on that exact page in the new deck after swap.

Screenshot → `docs/superpowers/specs/screenshots/dbuf-task-6-click.png`.

---

## Task 7: Wire trigger — mtime same-deck refresh [VERIFY]

The `decks_updated` WS handler currently calls `window.loadPdf(...)` directly when the active deck's `downloaded_at` changed. Replace with `prefetchInto`, passing a JIT `getPage` so the user's latest scroll wins.

**Files:**
- Modify: `static/participant.html:2562-2572` (`decks_updated` branch that re-loads the active deck)

- [ ] **Step 7.1: Update `decks_updated` handler**

Find the block at lines 2560-2573:

```js
        loadSlidesCatalog().then(function() {
          _applyHostSlideFollow(_hostSlidesCurrent).catch(function() {});
          if (activeRefreshed) {
            var activeSlide = _slidesCatalog.find(function(s) { return s.slug === activeSlug; });
            if (activeSlide) {
              var currentPage = _getCurrentSlidesPage() || 1;
              var freshDAt = (_slidesCacheStatus[activeSlug] || {}).downloaded_at || null;
              window.loadPdf(activeSlide.url, activeSlug, freshDAt, currentPage).then(function() {
                _applyHostSlideFollow(_hostSlidesCurrent).catch(function() {});
                if (refreshOverlay) refreshOverlay.style.display = 'none';
              });
            }
          }
        }).catch(function() {});
```

Replace with:

```js
        loadSlidesCatalog().then(function() {
          _applyHostSlideFollow(_hostSlidesCurrent).catch(function() {});
          if (activeRefreshed) {
            var activeSlide = _slidesCatalog.find(function(s) { return s.slug === activeSlug; });
            if (activeSlide) {
              var freshDAt = (_slidesCacheStatus[activeSlug] || {}).downloaded_at || null;
              var frontReady = !!(window.Slides && window.Slides.front && window.Slides.front.pdfDoc);
              if (frontReady && window.prefetchInto) {
                window.prefetchInto({
                  url: activeSlide.url,
                  slug: activeSlug,
                  downloadedAt: freshDAt,
                  // JIT: read user's latest scroll position right before swap.
                  getPage: function() { return _getCurrentSlidesPage() || 1; },
                }).then(function() {
                  _applyHostSlideFollow(_hostSlidesCurrent).catch(function() {});
                  // prefetchInto manages slide-refresh-overlay; nothing to clear here.
                });
              } else if (window.loadPdf) {
                var currentPage = _getCurrentSlidesPage() || 1;
                window.loadPdf(activeSlide.url, activeSlug, freshDAt, currentPage).then(function() {
                  _applyHostSlideFollow(_hostSlidesCurrent).catch(function() {});
                  if (refreshOverlay) refreshOverlay.style.display = 'none';
                });
              }
            }
          }
        }).catch(function() {});
```

Note: the existing `refreshOverlay.style.display = 'none'` cleanup runs only on the non-double-buffer fallback; in the double-buffer path, `prefetchInto`'s `finally` block hides it.

- [ ] **Step 7.2: Commit and push**

```bash
git add static/participant.html
git commit -m "feat(slides): wire mtime same-deck refresh to double-buffer

decks_updated handler now uses prefetchInto with a JIT getPage closure
so if the participant scrolls during the prefetch, the latest position
wins — they end up on the page they were viewing, not the one they
were on when the WS message arrived.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push origin master
```

- [ ] **Step 7.3: Wait for deploy.**

- [ ] **Step 7.4: [VERIFY] Manual test in prod — mtime refresh**

1. Open participant on `$WORKSHOP_SERVER_URL/<session>`. Open the active deck. Scroll to page 5.
2. As trainer, re-upload the PPTX (or trigger any change that bumps `downloaded_at`).
3. **Expected:** old slide stays visible. Top-left badge appears. After daemon-download + client-prefetch finish, swap happens — content updated, scroll still at page 5.
4. **JIT test:** repeat but during the prefetch, scroll to page 8 inside the still-visible old deck. After swap, you should be on page 8, not page 5.
5. DevTools console: no errors.

Screenshot → `docs/superpowers/specs/screenshots/dbuf-task-7-mtime.png`.

---

## Task 8: Wire trigger — host-follow new deck [VERIFY]

`_applyHostSlideFollow` already calls `selectTopic` when the host has moved to a different deck and follow is enabled. Since Task 6 made `selectTopic` use the double-buffer path when a front slide exists, **this trigger already works** after Task 6. But: `_applyHostSlideFollow` passes a `targetPage` from the host's current page, and we need to make sure that flows through `prefetchInto` correctly.

Read the current `_applyHostSlideFollow` body (lines 937-955) — it calls `selectTopic(topicEl || …, null, targetSlide, targetPage)`. The 4th argument is `targetPageOverride` which Task 6's refactor preserves into `targetPage` and captures into `prefetchInto`. **No code change required** for this trigger to start using double-buffer.

This task is purely manual verification.

- [ ] **Step 8.1: [VERIFY] Manual test in prod — host-follow new deck**

1. Open participant on `$WORKSHOP_SERVER_URL/<session>`. Enable follow (`slides-follow-checkbox`).
2. Have the host (separate browser window with host login) move to deck B at page 7.
3. **Expected:** participant's view of deck A stays visible. Top-left badge appears. After prefetch, atomic swap to deck B at page 7. Zero blank.
4. Repeat with host moving to deck C at page 3. Same behavior.

Screenshot → `docs/superpowers/specs/screenshots/dbuf-task-8-host-follow.png`.

- [ ] **Step 8.2: If no code change needed, no commit. Otherwise, fix and commit.**

---

## Task 9: Error path + race condition verification [VERIFY]

No code changes — purely manual verification of behaviors built in earlier tasks.

- [ ] **Step 9.1: [VERIFY] Failure path**

1. Open participant. Load deck A. Open DevTools Network tab.
2. Right-click the deck B request URL pattern and "Block request URL" (or use the Network throttling → Offline temporarily).
3. Click deck B.
4. **Expected:** deck A stays visible. Top-left badge appears, then disappears. Toast appears: "Slides nu s-au putut încărca. Reia când vrei."
5. Unblock URL. Click deck B again. Loads normally via double-buffer.

Screenshot → `docs/superpowers/specs/screenshots/dbuf-task-9-error.png`.

- [ ] **Step 9.2: [VERIFY] Latest-wins race**

1. Open participant. Load deck A.
2. Throttle network in DevTools to "Slow 3G" to make prefetches noticeable.
3. Click deck B → immediately click deck C → immediately click deck D, all within 1s.
4. **Expected:** final visible is deck D. Intermediate swaps to B or C should NOT happen. Console may show the aborted prefetches (silent — no toast).

Screenshot → `docs/superpowers/specs/screenshots/dbuf-task-9-race.png`.

- [ ] **Step 9.3: [VERIFY] Memory check**

1. Open participant. Load deck A.
2. DevTools → Performance → Memory → take heap snapshot (label "before").
3. Click between decks 20 times.
4. Take another heap snapshot ("after"). Diff.
5. **Expected:** no `pdfDoc`-related growth. The `PDFDocument` count should stay at 1 (the current front).

Screenshot → `docs/superpowers/specs/screenshots/dbuf-task-9-memory.png`.

---

## Task 10: Final polish + done [VERIFY]

- [ ] **Step 10.1: Final smoke check across all triggers**

Re-run the verification steps from Tasks 6, 7, 8 back-to-back to confirm no regression introduced by later tasks. All three triggers should produce identical UX: old slide stays visible, badge top-left, atomic swap.

- [ ] **Step 10.2: Mark spec as implemented**

Append to `docs/superpowers/specs/2026-05-13-participant-slides-double-buffer-design.md`:

```markdown
## Implementation status

Implemented and deployed to production on 2026-05-13.
Implementation plan: [`docs/superpowers/plans/2026-05-13-participant-slides-double-buffer.md`](../plans/2026-05-13-participant-slides-double-buffer.md).
Manual verification screenshots: `docs/superpowers/specs/screenshots/dbuf-task-*.png`.
```

Commit and push:

```bash
git add docs/superpowers/specs/2026-05-13-participant-slides-double-buffer-design.md docs/superpowers/specs/screenshots/
git commit -m "docs(slides): mark double-buffer spec as implemented

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push origin master
```

---

## Self-review checklist (for the engineer executing this plan)

Before declaring done, confirm:

- [ ] All 3 triggers (host-follow new deck, mtime refresh, manual click) keep the old slide visible during prefetch.
- [ ] `#pdf-check-overlay` centered loader appears **only on first-time** slides view, never on subsequent swaps.
- [ ] `#slide-refresh-overlay` top-left badge appears on every prefetch and disappears on every swap or error.
- [ ] On error: toast appears, front buffer untouched, retry via topic click works.
- [ ] Latest-wins: rapid trigger changes do not show intermediate slides.
- [ ] Memory: no `PDFDocument` leak after 20 deck switches.
- [ ] Annotation links inside slides still navigate within the deck (test by clicking a TOC link in a slide).
- [ ] Zoom (`pdfZoom`) still works (single-buffer, may flicker — acceptable).
- [ ] DevTools console: no errors during any of the scenarios above.
- [ ] All screenshots saved under `docs/superpowers/specs/screenshots/dbuf-task-*.png`.
