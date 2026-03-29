# Slides Tab + Host Inactivity Auto-Return — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 👨🏻‍🏫 Slides tab (first, leftmost) to the host panel that returns participants to slide-browsing mode, and replace the existing 30-second conference-only auto-return timer with a new 6-minute inactivity system (3-min warning modal → 3-min countdown → auto-switch) that works in all modes.

**Architecture:** Pure client-side change in `host.html` and `host.js`. The Slides tab calls `switchTab('none')` like the old hidden Hello tab. The inactivity module registers `mousemove`/`click`/`keydown` listeners on `document` and manages a full-screen blocking modal overlay with an amber countdown timer. No backend changes required.

**Tech Stack:** Vanilla JS (ES6), plain HTML5, inline CSS in host.html for the new modal.

---

## Files to Modify

| File | What changes |
|------|-------------|
| `static/host.html` | Replace hidden `tab-hello` with visible `tab-slides`; add inactivity modal HTML |
| `static/host.js` | Update `tab-hello` → `tab-slides` refs in `switchTab` and `updateCenterPanel`; remove old auto-return timer; add new inactivity module |

No new files. No backend changes. No `host.css` changes needed (new modal styled inline).

---

## Task 1: Replace tab-hello with tab-slides in host.html

**Files:**
- Modify: `static/host.html:28`

### Steps

- [ ] **1.1 Replace the hidden Hello tab button with the visible Slides tab**

In `static/host.html` line 28, replace:
```html
<button class="tab-btn" id="tab-hello" onclick="switchTab('none')" style="display:none"><span class="tab-icon">👋</span>Hello</button>
```
with:
```html
<button class="tab-btn" id="tab-slides" onclick="switchTab('none')"><span class="tab-icon">👨🏻‍🏫</span>Slides</button>
```

Note: no `style="display:none"` — Slides tab is always visible. It sits left of Poll, separated by the natural tab order.

- [ ] **1.2 Verify in browser**

Start server: `python3 -m uvicorn main:app --reload --port 8000`
Open http://localhost:8000/host — confirm 👨🏻‍🏫 Slides tab is visible as the first tab to the left of 📊 Poll.

---

## Task 2: Update all tab-hello references to tab-slides

**Files:**
- Modify: `static/host.js` — three locations: `switchTab`, `updateCenterPanel`, `applyConferenceLayout`

Search for every occurrence of `tab-hello` in `host.js` — there are exactly three:

### Steps

- [ ] **2.1 Update switchTab (~line 1982-1983)**

Find:
```javascript
const helloTab = document.getElementById('tab-hello');
if (helloTab) helloTab.classList.toggle('active', tab === 'none');
```
Replace with:
```javascript
const slidesTab = document.getElementById('tab-slides');
if (slidesTab) slidesTab.classList.toggle('active', tab === 'none');
```

- [ ] **2.2 Update updateCenterPanel (~line 2043)**

Find (inside `updateCenterPanel`):
```javascript
const helloTab = document.getElementById('tab-hello');
// ... helloTab.classList.toggle('active', currentActivity === 'none')
```
Replace `getElementById('tab-hello')` with `getElementById('tab-slides')`, rename local variable to `slidesTab`.

- [ ] **2.3 Clean up applyConferenceLayout (~lines 1051-1082)**

`applyConferenceLayout` has logic that showed `tab-hello` in conference mode and hid it in workshop mode. Since `tab-slides` is always visible in all modes, simply **delete** these three lines entirely:
```javascript
const helloTab = document.getElementById('tab-hello');
// ...
if (helloTab) helloTab.style.display = '';   // conference branch — delete
// ...
if (helloTab) helloTab.style.display = 'none'; // workshop branch — delete
```

- [ ] **2.3 Verify Slides tab highlights correctly**

In browser at http://localhost:8000/host:
- Click 👨🏻‍🏫 Slides → tab gets the active underline
- Click 📊 Poll → Poll gets active, Slides loses it
- Refresh page (server broadcasts `current_activity = none` on reconnect) → Slides tab should be active on load

---

## Task 3: Remove the old auto-return timer

**Files:**
- Modify: `static/host.js` — remove ~30 lines across 3 locations

The existing system: a 30-second conference-only timer (`AUTO_RETURN_DELAY = 30000`) with no warning. It is replaced entirely by the new inactivity module in Task 4.

### Steps

- [ ] **3.1 Remove constants and variable declarations**

Find and delete these lines near the top of `host.js` (around line 35-38):
```javascript
let _autoReturnTimer = null;
const AUTO_RETURN_DELAY = 30000; // 30 seconds
```
(`_currentActivity` at line 3045 must be kept — it's used by `switchTab`.)

- [ ] **3.2 Remove the three timer functions (lines 3043-3068)**

Delete the entire block:
```javascript
// ── Auto-return to Hello tab (conference mode only) ──

function _resetAutoReturn() { ... }
function startAutoReturnTimer() { ... }
function stopAutoReturnTimer() { ... }
```

- [ ] **3.3 Remove the two call sites**

Find the two usages (around lines 1069 and 1085):
```javascript
startAutoReturnTimer();
```
and
```javascript
stopAutoReturnTimer();
```
Delete both call sites. Leave surrounding mode-switch logic intact.

- [ ] **3.4 Verify no JS errors**

Open http://localhost:8000/host — browser console should have no `startAutoReturnTimer is not defined` or similar errors. Switch mode between workshop/conference — no errors.

---

## Task 4: Add inactivity modal HTML to host.html

**Files:**
- Modify: `static/host.html` — add modal markup + styles before `</body>`

### Steps

- [ ] **4.1 Add modal HTML + inline styles**

Before the closing `</body>` tag in `static/host.html`, insert:

```html
<!-- Inactivity auto-return modal -->
<div id="inactivity-modal" style="display:none; position:fixed; inset:0; z-index:9999;
     background:rgba(0,0,0,0.75); align-items:center; justify-content:center;">
  <div style="background:#0f172a; border:2px solid #f59e0b; border-radius:20px;
       padding:36px 48px; text-align:center; max-width:320px;
       box-shadow:0 0 60px rgba(245,158,11,0.35), 0 24px 48px rgba(0,0,0,0.6);">
    <div style="font-size:2.4rem; margin-bottom:12px;">💤</div>
    <div style="color:#fbbf24; font-weight:700; font-size:1.05rem; margin-bottom:16px;">Are you still there?</div>
    <div id="inactivity-timer" style="font-size:4rem; font-weight:800; color:#f59e0b;
         font-variant-numeric:tabular-nums; line-height:1; margin-bottom:14px;">3:00</div>
    <div style="color:#475569; font-size:.78rem;">Move your mouse to stay here</div>
  </div>
</div>
```

- [ ] **4.2 Verify modal renders**

Temporarily change `display:none` to `display:flex` in the modal div, reload http://localhost:8000/host — confirm full-screen amber overlay with 💤 icon and "3:00" timer appears, blocking the host UI. Revert `display:flex` back to `display:none` after confirming.

---

## Task 5: Implement the inactivity detection module in host.js

**Files:**
- Modify: `static/host.js` — add ~70 lines at the end of the file (before the final `})` or after the deleted auto-return block)

### Steps

- [ ] **5.1 Add the inactivity module**

Add the following block to `static/host.js` (at the bottom, after the removed auto-return timer section):

```javascript
// ── Host inactivity auto-return (all modes) ──
// After 3 min idle during an activity → show warning modal with 3-min countdown
// Any mouse/key activity resets the full 6-min timer
// After 6 min total idle → switchTab('none')

const INACTIVITY_WARN_MS  = 3 * 60 * 1000;  // 3 minutes → show modal
const INACTIVITY_TOTAL_MS = 6 * 60 * 1000;  // 6 minutes → auto-switch

let _inactivityWarnTimer   = null;
let _inactivitySwitchTimer = null;
let _inactivityModalVisible = false;
let _inactivityCountdownInterval = null;

function _showInactivityModal() {
  _inactivityModalVisible = true;
  const modal = document.getElementById('inactivity-modal');
  if (modal) modal.style.display = 'flex';
  _startModalCountdown();
}

function _hideInactivityModal() {
  _inactivityModalVisible = false;
  const modal = document.getElementById('inactivity-modal');
  if (modal) modal.style.display = 'none';
  clearInterval(_inactivityCountdownInterval);
  _inactivityCountdownInterval = null;
}

function _startModalCountdown() {
  const timerEl = document.getElementById('inactivity-timer');
  let remaining = INACTIVITY_WARN_MS; // 3 minutes in ms
  const tick = () => {
    remaining -= 1000;
    if (remaining <= 0) remaining = 0;
    const m = Math.floor(remaining / 60000);
    const s = Math.floor((remaining % 60000) / 1000);
    if (timerEl) timerEl.textContent = `${m}:${s.toString().padStart(2, '0')}`;
  };
  tick();
  _inactivityCountdownInterval = setInterval(tick, 1000);
}

function _resetInactivityTimer() {
  // Called on any user activity
  clearTimeout(_inactivityWarnTimer);
  clearTimeout(_inactivitySwitchTimer);
  if (_inactivityModalVisible) _hideInactivityModal();

  if (_currentActivity === 'none') return; // not tracking when on Slides

  // Restart full 6-min cycle
  _inactivityWarnTimer = setTimeout(_showInactivityModal, INACTIVITY_WARN_MS);
  _inactivitySwitchTimer = setTimeout(() => {
    _hideInactivityModal();
    switchTab('none');
  }, INACTIVITY_TOTAL_MS);
}

function startInactivityTracking() {
  ['mousemove', 'click', 'keydown'].forEach(evt =>
    document.addEventListener(evt, _resetInactivityTimer, { passive: true })
  );
  _resetInactivityTimer(); // arm the timers immediately
}

function stopInactivityTracking() {
  clearTimeout(_inactivityWarnTimer);
  clearTimeout(_inactivitySwitchTimer);
  _hideInactivityModal();
  ['mousemove', 'click', 'keydown'].forEach(evt =>
    document.removeEventListener(evt, _resetInactivityTimer)
  );
}
```

- [ ] **5.2 Start tracking at global scope**

`host.js` has no `DOMContentLoaded` handler — it runs as an inline script. Add a single call at the **bottom of the file** (after all function definitions, replacing the removed `startAutoReturnTimer()` call):
```javascript
startInactivityTracking();
```
This is safe — `_resetInactivityTimer` returns early if `_currentActivity === 'none'`, so tracking is a no-op until an activity starts.

- [ ] **5.3 Reset timer when activity changes**

In `switchTab()`, after `_currentActivity = tab;`, add:
```javascript
_resetInactivityTimer();
```
This re-arms the timer for the new activity (or stops it if switching to Slides/none).

- [ ] **5.4 Manual smoke test**

To test without waiting 3 minutes, temporarily set constants to short values in browser devtools console:
```javascript
// Paste in browser console to test quickly:
INACTIVITY_WARN_MS  = 5000;   // won't work — const, but you can test by patching
// Instead: open devtools, add breakpoint, or temporarily change the values in the file to 5000ms
```

Better approach — temporarily edit the constants to `5000` and `10000` (5s and 10s), reload, switch to Poll tab, leave mouse idle:
- At 5s: modal should appear with 5s countdown
- Move mouse: modal disappears, timer resets
- Stay idle for 10s total: `switchTab('none')` fires, Slides tab becomes active
- Revert constants to `3 * 60 * 1000` and `6 * 60 * 1000` before committing.

- [ ] **5.5 Commit**

```bash
git add static/host.html static/host.js
git commit -m "feat: add Slides tab and 6-min inactivity auto-return modal"
git push origin victorrentea/slides-tab-inactivity
```

---

## Done Criteria

- [ ] 👨🏻‍🏫 Slides tab is visible as the first tab in the host panel
- [ ] Clicking Slides tab sets `current_activity = none`, participants can browse slides
- [ ] Slides tab shows active underline when `current_activity === 'none'`
- [ ] No Hello tab visible anywhere
- [ ] During Poll/Q&A/etc.: after 3 min idle, full-screen amber modal appears with countdown
- [ ] Any mouse/key activity dismisses modal and resets full 6-min timer
- [ ] After 6 min total idle: auto-switches to Slides tab, activity data preserved
- [ ] No JS console errors in any mode (workshop or conference)
