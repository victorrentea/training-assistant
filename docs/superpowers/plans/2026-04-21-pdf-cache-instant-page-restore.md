# PDF Browser Cache + Instant Page Restore — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cache PDF bytes in IndexedDB so participants don't re-download decks, and eliminate the scroll-to-page artifact by hiding the viewer during rendering and revealing it already at the correct page.

**Architecture:** A new `PdfCache` JS object wraps IndexedDB reads/writes; `loadPdf()` gains `slug`, `downloadedAt`, and `targetPage` params; the existing `#pdf-check-overlay` covers both the server-check and render phases so the participant never sees page 1 before scrolling. Cache invalidation is driven by the existing `DecksUpdatedMsg` WS signal (online path) and `downloaded_at` mismatch (reconnect path).

**Tech Stack:** Vanilla JS, IndexedDB API, PDF.js 5.x (`pdfjsLib.getDocument({data: buffer})`), existing Railway/daemon backend (no backend changes needed).

---

## File Map

| File | Changes |
|---|---|
| `static/participant.html` | All changes — PdfCache module, loadPdf(), selectTopic(), _applyHostSlideFollow(), decks_updated handler |

No other files are touched. No backend changes required.

---

### Task 1: Add `PdfCache` IndexedDB module

**Files:**
- Modify: `static/participant.html` — add new `<script>` block just before the PDF.js `<script>` block (before line 473)

- [ ] **Step 1: Locate the insertion point**

  Find the opening of the PDF.js script block:
  ```
  import * as pdfjsLib from 'https://cdn.jsdelivr.net/npm/pdfjs-dist...
  ```
  It is inside a `<script type="module">` block. Insert a **new `<script>` block** directly before it.

- [ ] **Step 2: Insert the PdfCache module**

  Add this block immediately before the PDF.js `<script type="module">` block:

  ```html
  <script>
  var PdfCache = (function() {
    var DB_NAME = 'workshop-pdf-cache';
    var STORE = 'pdfs';
    function _open() {
      return new Promise(function(resolve, reject) {
        var req = indexedDB.open(DB_NAME, 1);
        req.onupgradeneeded = function(e) {
          e.target.result.createObjectStore(STORE, { keyPath: 'slug' });
        };
        req.onsuccess = function(e) { resolve(e.target.result); };
        req.onerror = function(e) { reject(e.target.error); };
      });
    }
    return {
      get: async function(slug, expectedDownloadedAt) {
        try {
          var db = await _open();
          var entry = await new Promise(function(resolve, reject) {
            var tx = db.transaction(STORE, 'readonly');
            var req = tx.objectStore(STORE).get(slug);
            req.onsuccess = function(e) { resolve(e.target.result); };
            req.onerror = function(e) { reject(e.target.error); };
          });
          if (!entry) return null;
          if (expectedDownloadedAt && entry.downloaded_at !== expectedDownloadedAt) return null;
          return entry.data;
        } catch(e) {
          console.warn('[PdfCache] get failed', e);
          return null;
        }
      },
      put: async function(slug, downloaded_at, buffer) {
        try {
          var db = await _open();
          await new Promise(function(resolve, reject) {
            var tx = db.transaction(STORE, 'readwrite');
            var req = tx.objectStore(STORE).put({ slug: slug, downloaded_at: downloaded_at, data: buffer });
            req.onsuccess = resolve;
            req.onerror = function(e) { reject(e.target.error); };
          });
        } catch(e) {
          console.warn('[PdfCache] put failed', e);
        }
      },
      invalidate: async function(slug) {
        try {
          var db = await _open();
          await new Promise(function(resolve, reject) {
            var tx = db.transaction(STORE, 'readwrite');
            var req = tx.objectStore(STORE).delete(slug);
            req.onsuccess = resolve;
            req.onerror = function(e) { reject(e.target.error); };
          });
        } catch(e) {
          console.warn('[PdfCache] invalidate failed', e);
        }
      }
    };
  })();
  </script>
  ```

- [ ] **Step 3: Verify in browser DevTools**

  Open participant page in browser → DevTools → Application → IndexedDB. After loading any slide deck, `workshop-pdf-cache` / `pdfs` store should appear with a slug entry. If it doesn't appear yet, that's fine — it gets populated in Task 2.

- [ ] **Step 4: Commit**

  ```bash
  git add static/participant.html
  git commit -m "feat(slides): add PdfCache IndexedDB module"
  ```

---

### Task 2: Rewrite `loadPdf()` — cache-first fetch, overlay, synchronous scroll

**Files:**
- Modify: `static/participant.html` lines 584–593 (the `window.loadPdf` function)

- [ ] **Step 1: Replace `window.loadPdf`**

  The current implementation (lines 584–593):
  ```js
  window.loadPdf = async function(url) {
    try {
      pdfDoc = await pdfjsLib.getDocument(url).promise;
      totalPages = pdfDoc.numPages;
      document.getElementById('pdf-pages').scrollTop = 0;
      await renderAllPages(currentScale);
    } catch(e) {
      console.error('PDF load error', e);
    }
  };
  ```

  Replace with:
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
      pdfDoc = await pdfjsLib.getDocument({ data: new Uint8Array(buffer) }).promise;
      totalPages = pdfDoc.numPages;
      await renderAllPages(currentScale);
      var page = (targetPage && targetPage > 1) ? targetPage : 1;
      if (page > 1) {
        var container = document.getElementById('pdf-pages');
        var section = container.querySelector('section[data-page="' + page + '"]');
        if (section) container.scrollTop = section.offsetTop;
      }
    } catch(e) {
      console.error('PDF load error', e);
    } finally {
      if (overlay) overlay.style.display = 'none';
    }
  };
  ```

  Key changes:
  - `slug`, `downloadedAt`, `targetPage` params (all optional for backwards compat)
  - Overlay shown at start, hidden in `finally`
  - `PdfCache.get` checked first; falls back to `fetch(url)`
  - Passes `{data: new Uint8Array(buffer)}` to PDF.js (bytes, not URL)
  - Synchronous `scrollTop` assignment after render — no `setTimeout`
  - Removed `scrollTop = 0`

- [ ] **Step 2: Smoke test in browser**

  Open the participant page. Select any slide deck. Verify:
  - Spinner appears while loading
  - Slide content renders
  - Spinner disappears
  - Page 1 is visible (targetPage not yet passed — comes in Task 3+)
  - DevTools → Application → IndexedDB → `workshop-pdf-cache` has an entry

- [ ] **Step 3: Commit**

  ```bash
  git add static/participant.html
  git commit -m "feat(slides): loadPdf() uses IndexedDB cache + overlay + synchronous scroll"
  ```

---

### Task 3: Update `selectTopic()` — pass slug/downloadedAt/targetPage, remove setTimeout

**Files:**
- Modify: `static/participant.html` — `selectTopic` function (around lines 1438–1483)

- [ ] **Step 1: Add `targetPageOverride` param and update the `loadPdf` call**

  Current `selectTopic` signature: `async function selectTopic(el, event, slide)`
  New: `async function selectTopic(el, event, slide, targetPageOverride)`

  Find this block inside `selectTopic` (around line 1452):
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
      } finally {
        if (_checkOverlay) { _checkOverlay.style.display = 'none'; }
      }
    }
    var dlUrl = slide.url + (slide.url.includes('?') ? '&' : '?') + 'download=1';
    var dlBtn = document.getElementById('pdf-download');
    if (dlBtn) { dlBtn.href = dlUrl; dlBtn.setAttribute('download', slide.name || ''); }
    await window.loadPdf(slide.url);
    _activeSlideId = slide._id || null;
    _activeSlideSlug = slide.slug || null;
    if (_activeSlideSlug) LS.setActiveSlide(_activeSlideSlug);
    // Restore last viewed page from localStorage
    if (slide.slug) {
      var storedPage = parseInt(localStorage.getItem('workshop_slide_page:' + slide.slug) || '1', 10);
      if (storedPage > 1) {
        setTimeout(function() { _scrollSlidesToPage(storedPage); }, 300);
      }
    }
  }
  ```

  Replace with:
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

  Changes:
  - Removed `finally` overlay hide (loadPdf handles it)
  - Added `downloadedAt` from `_slidesCacheStatus`
  - Added `targetPageOverride` param → falls back to localStorage stored page
  - Removed `setTimeout(_scrollSlidesToPage, 300)` block entirely

- [ ] **Step 2: Test in browser**

  1. Load a slide deck — you should land on the last page you were on (from localStorage), with no visible scroll.
  2. Navigate to page 5, reload the browser, re-open the deck — should restore to page 5 instantly.
  3. DevTools → Application → IndexedDB — entry for that slug should exist.

- [ ] **Step 3: Commit**

  ```bash
  git add static/participant.html
  git commit -m "feat(slides): selectTopic passes slug/downloadedAt/targetPage to loadPdf"
  ```

---

### Task 4: Update `_applyHostSlideFollow()` — eliminate 350 ms setTimeout

**Files:**
- Modify: `static/participant.html` — `_applyHostSlideFollow` function (around lines 795–819)

- [ ] **Step 1: Replace the deck-switch branch**

  Current (lines 804–813):
  ```js
  if (_activeSlideId !== targetSlide._id) {
    await selectTopic(topicEl || document.querySelector('.topic-item'), null, targetSlide);
    // Delay > 300ms so we fire after selectTopic's stored-page restoration,
    // which otherwise overrides the host's current page.
    var _tp = targetPage;
    setTimeout(function() {
      _scrollSlidesToPage(_tp) || setTimeout(function() { _scrollSlidesToPage(_tp); }, 200);
    }, 350);
    return;
  }
  ```

  Replace with:
  ```js
  if (_activeSlideId !== targetSlide._id) {
    await selectTopic(topicEl || document.querySelector('.topic-item'), null, targetSlide, targetPage);
    return;
  }
  ```

  The `targetPageOverride` param added in Task 3 ensures `loadPdf` receives the host's page, overriding any localStorage restore. The 350 ms hack is gone.

- [ ] **Step 2: Test follow mode in browser**

  Open two browser tabs — one as host (http://localhost:8081/), one as participant.
  1. Host switches to a different deck → participant should load that deck and land on the host's current page with no scroll animation.
  2. Host changes page within the same deck → participant smooth-scrolls to that page (same-deck path is unchanged — still uses `_scrollSlidesToPage` with smooth behavior).

- [ ] **Step 3: Commit**

  ```bash
  git add static/participant.html
  git commit -m "feat(slides): _applyHostSlideFollow passes host page directly to selectTopic"
  ```

---

### Task 5: Update `decks_updated` handler — invalidate cache, remove URL cache-buster

**Files:**
- Modify: `static/participant.html` — `decks_updated` case in WS message handler (around lines 2368–2416)

- [ ] **Step 1: Add cache invalidation and remove `?v=Date.now()` reload**

  Two edits in the `decks_updated` IIFE.

  **Edit A** — Insert the invalidation loop immediately after the `var activeRefreshed = ...` line (around line 2384), BEFORE the merge block that updates `_slidesCacheStatus`. This ordering is critical: the old status values must be read before the merge overwrites them.

  After this line:
  ```js
  var activeRefreshed = activeSlug && incomingDecks && window.loadPdf &&
    newDownloadedAt && (newDownloadedAt !== prevDownloadedAt);
  ```

  Insert:
  ```js
  // Invalidate IDB cache for slugs whose downloaded_at changed.
  // Must run BEFORE the merge below overwrites _slidesCacheStatus.
  if (incomingDecks && typeof incomingDecks === 'object') {
    Object.keys(incomingDecks).forEach(function(s) {
      var newDAt = (incomingDecks[s] || {}).downloaded_at;
      var oldDAt = (_slidesCacheStatus[s] || {}).downloaded_at;
      if (newDAt && newDAt !== oldDAt) PdfCache.invalidate(s);
    });
  }
  ```

  **Edit B** — Replace the `loadSlidesCatalog().then(...)` block (around lines 2404–2415):
  ```js
  loadSlidesCatalog().then(function() {
    _applyHostSlideFollow(_hostSlidesCurrent).catch(function() {});
    if (activeRefreshed) {
      var activeSlide = _slidesCatalog.find(function(s) { return s.slug === activeSlug; });
      if (activeSlide) {
        window.loadPdf(activeSlide.url + (activeSlide.url.indexOf('?') >= 0 ? '&' : '?') + 'v=' + Date.now()).then(function() {
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

  Changes:
  - Invalidation runs before the `_slidesCacheStatus` merge (correct ordering)
  - Active-deck reload passes `slug`, `freshDAt` (post-merge value), `currentPage` — no URL cache-buster
  - Cache miss is guaranteed because the entry was just invalidated in Edit A

- [ ] **Step 2: Test cache invalidation end-to-end**

  This requires the daemon running locally:
  1. Open participant page, load a slide deck — it should cache in IndexedDB.
  2. In the host panel, trigger a PPTX re-download (or manually call the daemon endpoint).
  3. Watch browser DevTools Network tab — the PDF should be re-fetched (cache miss) and the participant should stay on their current page after the reload.

- [ ] **Step 3: Commit**

  ```bash
  git add static/participant.html
  git commit -m "feat(slides): decks_updated invalidates IDB cache; removes URL cache-buster"
  ```

---

### Task 6: Final manual verification + push

- [ ] **Verify: no scroll artifact on deck load**
  - Open participant page, pick any slide deck → spinner → correct page, no scroll
  - Switch to another deck → spinner → page 1 (or last viewed) with no scroll animation
  - Follow host who switches deck → spinner → host's page, no scroll

- [ ] **Verify: IndexedDB caching works across sessions**
  - Load a deck, close the tab, reopen participant page, pick same deck → loads instantly (no network request in DevTools)

- [ ] **Verify: cache invalidation works (WS path)**
  - Daemon must be running. Trigger a PDF re-download for the active deck.
  - DevTools → Network → confirm PDF is re-fetched (not served from cache)

- [ ] **Verify: cache invalidation works (reconnect path)**
  - In DevTools → Application → IndexedDB → manually set `downloaded_at` to an old value for a slug
  - Reload page → load that deck → should re-fetch (mismatch detected)

- [ ] **Push to master**

  ```bash
  git push origin master
  ```
