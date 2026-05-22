# Participant Content Zoom — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `Ctrl + mouse wheel` zoom for the participant Notes, AI Summary, and Agenda views — single shared zoom factor 50 %–300 % persisted in `localStorage`, left nav and other views unaffected.

**Architecture:** A CSS custom property `--participant-zoom` on `:root` multiplies the per-view font-size baseline. A small JS module attaches a `wheel` listener to the three view roots only, intercepts `ctrlKey` wheel events, adjusts the variable by ±0.1 within `[0.5, 3.0]`, and writes the value to `localStorage`. Loaded at boot from `localStorage` (default `1.0`).

**Tech Stack:** Plain HTML + vanilla JS (no build step), CSS custom properties, `localStorage`. All changes live in `static/participant.html`.

**Spec:** `docs/superpowers/specs/2026-05-22-participant-content-zoom-design.md`

**Testing approach:** Per the spec, this is a pure-UI keyboard interaction. Verification is manual in a local browser. No automated test is added.

---

## File Map

- **Modify** `static/participant.html`:
  - **CSS** (first `<style>` block, around lines 11–36): add three font-size rules and the `:root --participant-zoom` default
  - **HTML** (lines 474 and 490): remove `font-size:120%` from the inline `style` attribute of `#summary-view` and `#agenda-view`
  - **JS** (near other view-level globals around lines 950–965 and the `DOMContentLoaded` listener around line 3053): add zoom constants, load/apply/handler/install functions, call `_installContentZoom()` from the existing `DOMContentLoaded` handler

No other files are touched.

---

## Task 1: Move the 120 % baseline into CSS and add the zoom variable

**Files:**
- Modify: `static/participant.html:11-36` (first `<style>` block)
- Modify: `static/participant.html:474` (remove inline `font-size:120%` from `#summary-view`)
- Modify: `static/participant.html:490` (remove inline `font-size:120%` from `#agenda-view`)

- [ ] **Step 1: Add CSS rules and the `--participant-zoom` default**

Insert the following inside the first `<style>` block (after the existing `body{visibility:hidden}` rule on line 12):

```css
:root{--participant-zoom:1}
#notes-content{font-size:calc(1rem * var(--participant-zoom))}
#summary-content{font-size:calc(1.2rem * var(--participant-zoom))}
#agenda-content{font-size:calc(1.2rem * var(--participant-zoom))}
```

- [ ] **Step 2: Strip `font-size:120%` from the `#summary-view` inline style**

Find line 474:

```html
<div id="summary-view" style="display:none;font-size:120%" class="relative h-full flex flex-col">
```

Change to:

```html
<div id="summary-view" style="display:none" class="relative h-full flex flex-col">
```

- [ ] **Step 3: Strip `font-size:120%` from the `#agenda-view` inline style**

Find line 490:

```html
<div id="agenda-view" style="display:none;font-size:120%" class="h-full overflow-y-auto px-16 py-12" onscroll="saveScroll('agenda',this)">
```

Change to:

```html
<div id="agenda-view" style="display:none" class="h-full overflow-y-auto px-16 py-12" onscroll="saveScroll('agenda',this)">
```

- [ ] **Step 4: Verify the baseline is unchanged visually**

Start the local server (if not already running) and open `http://localhost:8081/` as a participant. Switch to Notes, Summary, and Agenda views. Confirm:

- Notes text size matches what it was before
- Summary text size matches what it was before (120 % of base)
- Agenda text size matches what it was before (120 % of base)

If any view looks different in size at zoom = 1.0, the CSS rule or selector is wrong — fix before continuing.

- [ ] **Step 5: Commit**

```bash
git add static/participant.html
git commit -m "refactor(participant): move font-size baseline into CSS with --participant-zoom var"
```

---

## Task 2: Add the zoom JS — constants, load, apply, wheel handler, install

**Files:**
- Modify: `static/participant.html` (add functions in the JS section, near other view-level globals around lines 950–965)

- [ ] **Step 1: Locate insertion point**

Find the block around line 954:

```js
var _notesDirty = true;
var _summaryDirty = true;
```

We will add the zoom code immediately above this block, so the constants and helpers live with other view-level state.

- [ ] **Step 2: Insert the zoom module**

Immediately before `var _notesDirty = true;`, add:

```js
var ZOOM_KEY = 'participant:contentZoom';
var ZOOM_MIN = 0.5;
var ZOOM_MAX = 3.0;
var ZOOM_STEP = 0.1;

function _loadContentZoom() {
  var raw = localStorage.getItem(ZOOM_KEY);
  var z = parseFloat(raw);
  if (!isFinite(z) || z < ZOOM_MIN || z > ZOOM_MAX) z = 1.0;
  document.documentElement.style.setProperty('--participant-zoom', String(z));
  return z;
}

function _applyContentZoom(z) {
  z = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, Math.round(z * 10) / 10));
  document.documentElement.style.setProperty('--participant-zoom', String(z));
  localStorage.setItem(ZOOM_KEY, String(z));
  return z;
}

function _onContentZoomWheel(e) {
  if (!e.ctrlKey) return;
  e.preventDefault();
  var current = parseFloat(
    getComputedStyle(document.documentElement).getPropertyValue('--participant-zoom')
  ) || 1.0;
  var delta = e.deltaY < 0 ? ZOOM_STEP : -ZOOM_STEP;
  _applyContentZoom(current + delta);
}

function _installContentZoom() {
  _loadContentZoom();
  ['notes-view', 'summary-view', 'agenda-view'].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) el.addEventListener('wheel', _onContentZoomWheel, { passive: false });
  });
}
```

- [ ] **Step 3: Verify the script parses**

Reload `http://localhost:8081/` in a browser. Open the DevTools console — there must be no syntax errors. The page must render normally.

If the page does not render or the console shows a parse error, fix it before continuing.

- [ ] **Step 4: Commit**

```bash
git add static/participant.html
git commit -m "feat(participant): add Ctrl+wheel content zoom module"
```

---

## Task 3: Install the zoom handler at boot

**Files:**
- Modify: `static/participant.html:3053-3058` (existing `DOMContentLoaded` listener)

- [ ] **Step 1: Locate the existing `DOMContentLoaded` handler**

Find lines 3053–3058:

```js
document.addEventListener('DOMContentLoaded', function() {
  var overlay = document.getElementById('pax-lb-overlay');
  if (overlay) overlay.addEventListener('click', function(e) {
    if (e.target === overlay) _hidePaxLb();
  });
});
```

- [ ] **Step 2: Add `_installContentZoom()` call**

Change to:

```js
document.addEventListener('DOMContentLoaded', function() {
  _installContentZoom();
  var overlay = document.getElementById('pax-lb-overlay');
  if (overlay) overlay.addEventListener('click', function(e) {
    if (e.target === overlay) _hidePaxLb();
  });
});
```

- [ ] **Step 3: Verify zoom is initialized at load**

Reload `http://localhost:8081/`. In DevTools console run:

```js
getComputedStyle(document.documentElement).getPropertyValue('--participant-zoom')
```

Expected: `" 1"` (the default — `_loadContentZoom` set it because no `localStorage` value exists yet).

Then run:

```js
localStorage.setItem('participant:contentZoom', '1.5'); location.reload();
```

After the reload, run the `getComputedStyle` line again. Expected: `" 1.5"`. This confirms persistence is round-tripping.

Clean up:

```js
localStorage.removeItem('participant:contentZoom');
```

- [ ] **Step 4: Commit**

```bash
git add static/participant.html
git commit -m "feat(participant): wire content zoom installer into DOMContentLoaded"
```

---

## Task 4: Manual end-to-end verification

**Files:** None — verification only.

- [ ] **Step 1: Reload as a participant**

Open `http://localhost:8081/` in a fresh tab (or clear `participant:contentZoom` first). Confirm everything renders normally and the zoom factor is `1`.

- [ ] **Step 2: Ctrl + wheel up in Notes**

Switch to Notes view. Hold `Ctrl` and scroll the wheel up. Expected:

- Browser-native zoom does NOT trigger (the page chrome stays the same size)
- Notes text grows by 10 % per wheel tick
- Repeating reaches a clamp at 300 % — text stops growing

- [ ] **Step 3: Ctrl + wheel down in Notes**

Hold `Ctrl` and scroll the wheel down. Expected:

- Text shrinks by 10 % per wheel tick
- Clamps at 50 % — text stops shrinking further

- [ ] **Step 4: Cross-view consistency**

Switch to AI Summary. Expected: text is rendered at `1.2 × Z` of base (so at `Z = 1.0` it matches today's 120 %). Same for Agenda. Both views show the same zoom factor as Notes.

- [ ] **Step 5: Persistence across reload**

Set zoom to roughly 150 % via Ctrl + wheel, then reload the page. Expected: the zoom factor persists; Notes/Summary/Agenda all come up at the larger size immediately.

- [ ] **Step 6: Other views unaffected**

Switch to Activity, Slides, Feedback, Upload/Paste. Expected: all unchanged in size regardless of the zoom factor.

- [ ] **Step 7: Ctrl + wheel over the left nav**

Hover over the left navigation bar. Hold `Ctrl` and scroll. Expected: browser-native zoom DOES trigger (because the listener is attached only to the three view roots, not the nav).

If the browser-native zoom is undesirable here, that's a future enhancement — out of scope for this plan. Reset browser zoom via `Cmd/Ctrl + 0`.

- [ ] **Step 8: Plain wheel still scrolls**

Without `Ctrl`, scroll in Notes/Summary/Agenda. Expected: content scrolls normally; zoom is unchanged.

- [ ] **Step 9: Reset for production**

Clear the test zoom value so it does not surprise you later:

```js
localStorage.removeItem('participant:contentZoom'); location.reload();
```

- [ ] **Step 10: Push to master**

Per project workflow (push small changes directly):

```bash
git push origin master
```

- [ ] **Step 11: Wait for Railway deploy and verify in prod**

Per project rule (`feedback_wait_for_prod_deploy.md`, `feedback_verify_in_prod_always.md`), confirm the deploy is live at the production URL listed in `CLAUDE.md`:

1. Visit the production participant page.
2. Repeat steps 2, 4, and 5 there (Ctrl + wheel zooms in Notes; cross-view consistency in Summary/Agenda; persistence across reload).
3. If any check fails, do not mark the plan done — diagnose the prod-vs-local difference.

---

## Self-Review

**Spec coverage:**

- ✅ Three views affected: notes, summary, agenda — Task 1 CSS rules + Task 2 listener install
- ✅ Right pane only — listener attached only to `#notes-view`, `#summary-view`, `#agenda-view` (Task 2 step 2; Task 4 step 7)
- ✅ Ctrl + wheel only, no keyboard shortcuts, no UI button — `_onContentZoomWheel` checks `e.ctrlKey` and no other listeners or buttons are added
- ✅ Range 50 %–300 %, 10 % step — `ZOOM_MIN/MAX/STEP` constants and `_applyContentZoom` clamp
- ✅ Default 100 % — `_loadContentZoom` falls back to `1.0`
- ✅ Global shared zoom, persisted across reloads — single `localStorage` key `participant:contentZoom`, single CSS variable
- ✅ Suppress browser zoom always (option A) — `_onContentZoomWheel` always calls `preventDefault()` when `ctrlKey` is set, including at clamp boundaries
- ✅ Inline `font-size:120%` removed — Task 1 steps 2 and 3
- ✅ Baseline ratio preserved (notes 100 %, summary/agenda 120 % at Z = 1) — CSS uses `1rem` for notes and `1.2rem` for summary/agenda

**Placeholder scan:** none.

**Type consistency:** `_loadContentZoom`, `_applyContentZoom`, `_onContentZoomWheel`, `_installContentZoom` — all four function names are used consistently across Task 2 (definition) and Task 3 (invocation). `ZOOM_KEY` / `ZOOM_MIN` / `ZOOM_MAX` / `ZOOM_STEP` are all declared in Task 2 step 2.
