# Participant Onboarding Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dim the whole `participant.html` workshop view on first visit, keep the emoji reaction bar lit, show a motivational bubble above it; participant must press an emoji to dismiss. Persist a `localStorage` flag so it never shows again on the same browser. Rewire the bottom-right version line to reset only that flag, for easy testing.

**Architecture:** Pure front-end change inside a single file (`static/participant.html`). Two new DOM elements (overlay + tooltip) appended to `<body>`. Body class `onboarding-active` lifts the emoji bar wrapper above the overlay via a CSS z-index override. A single delegated click listener detects clicks inside the emoji bar or overflow popup and dismisses the overlay. No backend, no new endpoints, no new deps.

**Tech Stack:** Plain HTML + vanilla JS + Tailwind utility classes (already loaded). Playwright/pytest for the hermetic test.

**Reference spec:** `docs/superpowers/specs/2026-04-17-participant-onboarding-overlay-design.md`

---

### Task 1: Add CSS block for overlay, tooltip, bubble, arrow, and z-index override

**Files:**
- Modify: `static/participant.html` — the inline `<style>` block after line 74 (after `.avatar-swap` keyframes, before the `</style>` closing tag at line 74)

- [ ] **Step 1: Open the file and locate the first `<style>` closing tag**

Find the block starting at line 36 (`<style>`) and ending near line 74 (`</style>`). Insert the new rules before `</style>`.

- [ ] **Step 2: Append the onboarding CSS**

Insert right before the `</style>` that closes the styling block (near line 74):

```css
#onboarding-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 40;
  opacity: 0;
  transition: opacity 300ms ease;
  pointer-events: none;
}
#onboarding-overlay.visible { opacity: 1; }
#onboarding-overlay.hidden, #onboarding-tooltip.hidden { display: none; }

#onboarding-tooltip {
  position: fixed;
  bottom: calc(6rem + 4.5rem);
  right: 1.5rem;
  z-index: 51;
  opacity: 0;
  transform: translateY(8px);
  transition: opacity 300ms ease, transform 300ms ease;
  pointer-events: none;
}
#onboarding-tooltip.visible { opacity: 1; transform: translateY(0); }

.onboarding-bubble {
  position: relative;
  background: var(--color-primary, #4555ba);
  color: var(--color-on-primary, #fff);
  padding: 0.75rem 1.25rem;
  border-radius: 1rem;
  font-size: 0.95rem;
  font-weight: 600;
  max-width: 20rem;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
  line-height: 1.4;
}
.onboarding-arrow {
  position: absolute;
  bottom: -6px;
  right: 2rem;
  width: 12px;
  height: 12px;
  background: var(--color-primary, #4555ba);
  transform: rotate(45deg);
}

body.onboarding-active .absolute.bottom-6.right-6 { z-index: 50; }
```

Note on `.hidden`: Tailwind's `.hidden` rule is `display: none !important` and is already loaded. The override above is defensive in case the file-order load causes flicker; it also makes the class behavior explicit for this feature.

- [ ] **Step 3: Commit**

```bash
git add static/participant.html
git commit -m "onboarding: add CSS for overlay, tooltip, bubble, arrow, z-index lift"
```

---

### Task 2: Add overlay + tooltip DOM at the end of body

**Files:**
- Modify: `static/participant.html` — append just before `</body>`

- [ ] **Step 1: Locate the closing `</body>` tag**

Use Grep or read the last 20 lines of `static/participant.html` to find the `</body>` tag.

- [ ] **Step 2: Insert the two elements immediately before `</body>`**

```html
<!-- Onboarding overlay (workshop mode, first visit) -->
<div id="onboarding-overlay" class="hidden"></div>
<div id="onboarding-tooltip" class="hidden">
  <div class="onboarding-bubble">
    React as often as you can — tell me how you feel. Tap ☕ when you get tired.
  </div>
  <div class="onboarding-arrow"></div>
</div>
```

- [ ] **Step 3: Verify syntax with a browser load**

Run the daemon / hit the page and ensure no layout regressions appear. The elements are `.hidden` by default and have zero visual impact.

Use: `python3 -m daemon` in one terminal, open `http://localhost:1234/` in the browser. Confirm no console errors and no visible overlay.

- [ ] **Step 4: Commit**

```bash
git add static/participant.html
git commit -m "onboarding: add overlay + tooltip DOM (hidden by default)"
```

---

### Task 3: Add LS key, show/dismiss functions, and shouldShow gate

**Files:**
- Modify: `static/participant.html` — the `<script>` block that starts at line 1385, right after the `_isFirstVisit` / `LS_*` declarations (around line 1399)

- [ ] **Step 1: Locate insertion point**

Find the line `var LS_CUSTOM_NAME_KEY = 'workshop_custom_name';` (around line 1399). Insert after it.

- [ ] **Step 2: Insert the key and functions**

```js
var LS_ONBOARDING_KEY = 'workshop_onboarding_seen';

function _shouldShowOnboarding() {
  if (_isHostTab) return false;
  return !localStorage.getItem(LS_ONBOARDING_KEY);
}

function _showOnboarding() {
  document.body.classList.add('onboarding-active');
  var overlay = document.getElementById('onboarding-overlay');
  var tooltip = document.getElementById('onboarding-tooltip');
  if (!overlay || !tooltip) return;
  overlay.classList.remove('hidden');
  tooltip.classList.remove('hidden');
  requestAnimationFrame(function () {
    overlay.classList.add('visible');
    tooltip.classList.add('visible');
  });
}

function _dismissOnboarding() {
  if (!document.body.classList.contains('onboarding-active')) return;
  localStorage.setItem(LS_ONBOARDING_KEY, '1');
  var overlay = document.getElementById('onboarding-overlay');
  var tooltip = document.getElementById('onboarding-tooltip');
  if (overlay) overlay.classList.remove('visible');
  if (tooltip) tooltip.classList.remove('visible');
  setTimeout(function () {
    if (overlay) overlay.classList.add('hidden');
    if (tooltip) tooltip.classList.add('hidden');
    document.body.classList.remove('onboarding-active');
  }, 300);
}
```

- [ ] **Step 3: Verify the file still parses**

Reload the page. Open devtools console. Expected: no JS errors. Run in console: `typeof _shouldShowOnboarding` → should print `"function"`.

- [ ] **Step 4: Commit**

```bash
git add static/participant.html
git commit -m "onboarding: add LS key + show/dismiss/shouldShow functions"
```

---

### Task 4: Wire the delegated click listener for dismissal

**Files:**
- Modify: `static/participant.html` — append at the end of the final `<script>` block (before `</script>` that closes the main participant script, just after `function resetStatePrompt()` around line 1381 — note: this file has multiple `<script>` blocks; use the main one where `sendEmoji` lives and where `loadParticipantState` is defined)

- [ ] **Step 1: Locate the right script block**

Grep the file for `loadParticipantState` — that's the bottom `<script>` block. Insert near the top of that block (after the existing `var`/function declarations block, anywhere before the IIFE `(async function loadParticipantState()`) or at the end of the dismissal function definitions added in Task 3.

- [ ] **Step 2: Insert the listener**

```js
document.addEventListener('click', function (e) {
  if (!document.body.classList.contains('onboarding-active')) return;
  var bar = document.getElementById('emoji-main-bar');
  var overflow = document.getElementById('emoji-overflow');
  if ((bar && bar.contains(e.target)) || (overflow && overflow.contains(e.target))) {
    _dismissOnboarding();
  }
}, true);
```

The `true` third argument puts the listener on the capture phase — fires before `sendEmoji` / `addEmojiToBar` run, so dismissal state is correct by the time the rest of the app sees the click.

- [ ] **Step 3: Manual verify — listener is registered**

Reload the page. In devtools console, run:

```js
document.body.classList.add('onboarding-active');
document.getElementById('emoji-main-bar').querySelector('button').click();
document.body.classList.contains('onboarding-active');
```

Expected: the last line prints `false` after ~300ms (the dismiss ran). If it prints `true` immediately, the listener isn't firing — debug.

- [ ] **Step 4: Commit**

```bash
git add static/participant.html
git commit -m "onboarding: delegated click listener to dismiss on emoji press"
```

---

### Task 5: Hook the show call after loading screen hides

**Files:**
- Modify: `static/participant.html` — inside `loadParticipantState()`, right after `document.getElementById('loading-screen').style.display = 'none';` (around line 1664)

- [ ] **Step 1: Locate the exact line**

Find the line `document.getElementById('loading-screen').style.display = 'none';` in the `loadParticipantState` async IIFE (around line 1664).

- [ ] **Step 2: Insert the show call on the line after**

Change:

```js
    document.getElementById('loading-screen').style.display = 'none';
```

To:

```js
    document.getElementById('loading-screen').style.display = 'none';
    if (_shouldShowOnboarding()) _showOnboarding();
```

- [ ] **Step 3: Manual verify — first visit shows overlay**

Open the page in an incognito window (fresh localStorage). After the loading spinner disappears, the overlay should appear, bubble visible, emoji bar lit. Screenshot.

- [ ] **Step 4: Manual verify — returning participant does NOT see overlay**

Reload the same tab. Overlay should NOT appear (flag set by last test? — no, we only set the flag on dismissal. So at this point, the flag is still not set, so it will show again. To test returning-participant behavior, first dismiss by clicking an emoji, then reload.)

Actually execute: click any emoji button (dismisses and sets flag). Wait 300 ms. Reload. Expected: no overlay. Screenshot.

- [ ] **Step 5: Commit**

```bash
git add static/participant.html
git commit -m "onboarding: show overlay after loading screen hides (first visit only)"
```

---

### Task 6: Rewire the version line to reset only the onboarding flag

**Files:**
- Modify: `static/participant.html` — line 184 (onclick attribute + title) and the `LS.clear` function (around line 471) + add a new function near `resetStatePrompt`

- [ ] **Step 1: Add `resetOnboardingForTest` near `resetStatePrompt`**

Find `function resetStatePrompt() {` (line 1376). Add a new function right before it (or right after):

```js
function resetOnboardingForTest() {
  localStorage.removeItem(LS_ONBOARDING_KEY);
  location.reload();
}
```

- [ ] **Step 2: Rewire the `#deploy-age-line` onclick**

Find line 184:

```html
<div id="deploy-age-line" onclick="resetStatePrompt()" title="Click to reset local state"
```

Change to:

```html
<div id="deploy-age-line" onclick="resetOnboardingForTest()" title="Click to reset onboarding (for testing)"
```

- [ ] **Step 3: Add the onboarding key to `LS.clear` for consistency**

Find the `clear: function() {` inside the `LS` object (around line 471). Add a line removing the onboarding key alongside the other `localStorage.removeItem` calls:

```js
  clear: function() {
    localStorage.removeItem(LS.EMOJI_PROMOTED);
    localStorage.removeItem(LS.VIEW);
    localStorage.removeItem(LS.FOLLOW);
    localStorage.removeItem(LS.NOTES_UNREAD);
    localStorage.removeItem(LS.SUMMARY_UNREAD);
    localStorage.removeItem('workshop_onboarding_seen'); // onboarding flag
    // ... whatever else was already here, preserve it ...
  },
```

Preserve every existing line in `clear`. Only add the new `removeItem` call. Do not remove any existing call.

- [ ] **Step 4: Manual verify — click version line resets onboarding only**

Setup: with an already-dismissed onboarding (flag set, avatar assigned, maybe a promoted emoji). Click the version line in the bottom-right. Expected: page reloads, overlay appears again; avatar, name, promoted emojis are preserved.

Screenshot showing the overlay back on, and the same avatar/name in the sidebar.

- [ ] **Step 5: Commit**

```bash
git add static/participant.html
git commit -m "onboarding: rewire version line to reset only onboarding flag"
```

---

### Task 7: Add hermetic Playwright test

**Files:**
- Create: `tests/docker/test_participant_onboarding.py`

- [ ] **Step 1: Read existing test patterns**

Read `tests/docker/test_participant_interactions.py` and `tests/pages/participant_page.py` to understand: how a participant context is created, how `fresh_session` is used, how Playwright locators are resolved for emoji buttons. Reuse the same imports and conventions.

- [ ] **Step 2: Write the test file**

```python
"""
Hermetic E2E test: participant onboarding overlay.

- First visit (cleared storage) → overlay visible after loading screen hides.
- Click any emoji button → overlay dismissed, localStorage flag set.
- Reload → overlay does NOT reappear.
"""

import os
import sys
import time

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

from playwright.sync_api import sync_playwright, expect

from session_utils import fresh_session


BASE = "http://localhost:8000"


def test_onboarding_first_visit_shows_and_dismisses():
    session_id = fresh_session("OnboardingTest")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(f"{BASE}/{session_id}", wait_until="networkidle")

        # Wait for loading screen to hide and overlay to appear.
        overlay = page.locator("#onboarding-overlay")
        expect(overlay).to_have_class("visible", timeout=10000)

        # Tooltip is visible too.
        tooltip = page.locator("#onboarding-tooltip")
        expect(tooltip).to_have_class("visible")

        # Click any emoji button in the main bar.
        first_emoji = page.locator("#emoji-main-bar button").first
        first_emoji.click()

        # Overlay fades out (loses `visible` class) within 500 ms.
        time.sleep(0.6)
        overlay_class = overlay.get_attribute("class") or ""
        assert "visible" not in overlay_class, (
            f"overlay still has 'visible' class after dismissal: {overlay_class}"
        )

        # localStorage flag is set.
        flag = page.evaluate("() => localStorage.getItem('workshop_onboarding_seen')")
        assert flag == "1", f"expected flag '1', got {flag!r}"

        # Reload — overlay must NOT reappear.
        page.reload(wait_until="networkidle")
        time.sleep(0.5)
        overlay_class_after_reload = overlay.get_attribute("class") or ""
        assert "visible" not in overlay_class_after_reload, (
            f"overlay reappeared after reload: {overlay_class_after_reload}"
        )

        browser.close()
```

- [ ] **Step 3: Run the test hermetically**

```bash
cd /Users/victorrentea/workspace/training-assistant
bash tests/docker/run-hermetic.sh -k test_onboarding_first_visit_shows_and_dismisses -s
```

Expected: PASS. If `to_have_class("visible", ...)` fails with class `hidden visible`, use a regex matcher: `expect(overlay).to_have_class(re.compile(r"\bvisible\b"), timeout=10000)`.

- [ ] **Step 4: If test fails, debug with a screenshot**

If timing or class sync is flaky, add `page.screenshot(path="/tmp/ob-debug.png", full_page=True)` before the failing assertion.

- [ ] **Step 5: Commit**

```bash
git add tests/docker/test_participant_onboarding.py
git commit -m "onboarding: hermetic Playwright test (show, dismiss, persist)"
```

---

### Task 8: Manual QA pass with screenshots

- [ ] **Step 1: Fresh-storage run**

Open an incognito browser window. Navigate to the production or local participant URL. Wait for loading spinner to hide.

Expected: overlay dimmed at 50% opacity, emoji bar lit in bottom-right, bubble above bar with text *"React as often as you can — tell me how you feel. Tap ☕ when you get tired."*

**Screenshot.** Save to `/tmp/ob-step1-fresh.png` (or clipboard).

- [ ] **Step 2: Dismiss by clicking an emoji**

Click the ❤️ button (first in the bar). Expected: overlay fades out in ~300 ms, emoji float animation plays normally, reaction is sent to the backend (host sees it if connected).

**Screenshot** after dismissal.

- [ ] **Step 3: Reload — no reappearance**

Reload the page. Expected: no overlay.

**Screenshot.**

- [ ] **Step 4: Version-line reset**

Click the small version/age text in the bottom-right corner. Expected: no confirm, page reloads, overlay appears again. Avatar and name in the sidebar are the same as before the reset.

**Screenshot** after reload.

- [ ] **Step 5: Host tab — no overlay**

Open the host page (`/host/<session_id>`) in the same browser. Expected: no overlay even on first visit (host cookie → `_isHostTab` → `_shouldShowOnboarding` returns false). Navigate to participant page as a secondary tab from the host context.

Note: this test may be tricky to set up — host cookie is set on `/host` path. If the browser doesn't carry it to the participant URL, consider this low-priority; the code path is simple (one `if (_isHostTab) return false`) and the unit logic is trivial.

- [ ] **Step 6: Talk mode — page is unaffected**

If a talk-mode session is available, navigate there. Expected: `talk.html` is served (different layout, purple theme), no onboarding overlay, no console errors.

---

### Task 9: Push to master and verify production

- [ ] **Step 1: Confirm all tests pass locally**

```bash
bash tests/check-all.sh
```

Expected: green.

- [ ] **Step 2: Push**

```bash
git push origin master
```

- [ ] **Step 3: Wait for Railway deployment**

Railway auto-deploys on push; ~40-50 s. Use the `wait-for-deploy` skill or poll the deploy-info endpoint.

- [ ] **Step 4: Verify on production**

Open the production participant URL (see `$WORKSHOP_SERVER_URL` in `secrets.env`) in an incognito window. Expected: onboarding overlay appears. Click an emoji to dismiss. Reload — no overlay.

**Screenshot.**

- [ ] **Step 5: Record in backlog.md**

Add a single-line entry under today's date summarizing the feature (per CLAUDE.md convention — "Document direct requests: track feature changes and bug fixes in backlog.md").

Example line:

```
- 2026-04-17: Added onboarding overlay for first-time participants in workshop mode — dims screen, spotlights emoji bar, forces one interaction to dismiss. Version-line click now resets only the onboarding flag (for testing).
```

Commit + push.

---

## Self-review summary

**Spec coverage:**
- Lifecycle/trigger/suppression/dismissal/persistence → Tasks 3, 4, 5 ✓
- DOM → Task 2 ✓
- Styling + z-index stack → Task 1 ✓
- JS show/dismiss/should-show → Task 3 ✓
- Delegated click wiring → Task 4 ✓
- Debug affordance (version line rewire) → Task 6 ✓
- Entry point after loading screen → Task 5 ✓
- LS.clear update → Task 6 ✓
- Manual testing checklist → Task 8 ✓
- Hermetic Playwright test → Task 7 ✓
- Out-of-scope items (localization, analytics, A/B) → respected (not in any task) ✓

**Placeholder scan:** No TBDs. All code blocks are concrete.

**Type/name consistency:**
- `LS_ONBOARDING_KEY = 'workshop_onboarding_seen'` — same string used in `resetOnboardingForTest` (Task 6, Step 1) and `LS.clear` (Task 6, Step 3). ✓
- `_shouldShowOnboarding` / `_showOnboarding` / `_dismissOnboarding` — same names across Tasks 3, 4, 5. ✓
- `#onboarding-overlay`, `#onboarding-tooltip` — same IDs in CSS (Task 1), HTML (Task 2), JS (Task 3), test (Task 7). ✓
