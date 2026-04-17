# Participant Onboarding Overlay — Design

**Date:** 2026-04-17
**Scope:** `static/participant.html` (workshop mode only)
**Goal:** Push first-time participants to interact with the emoji reaction bar immediately on arrival. The screen dims; only the emoji bar stays lit; a motivational bubble points at it. The participant must press an emoji to continue.

---

## Motivation

The emoji reaction bar is the lowest-effort, highest-signal feedback channel in the app. It drives the coffee (☕) signal that tells the trainer when to take a break, and the heart/fire/thumbs that show what is landing. Today many first-time participants never notice the bar, especially on desktop where it sits unobtrusively in the bottom-right corner.

An onboarding moment on first visit — one that forces a single click — converts passive visitors into active reactors from minute one.

---

## Lifecycle

- **Trigger:** on `participant.html` load (workshop mode — served when `state.session_type != "talk"`), if `localStorage['workshop_onboarding_seen']` is not set.
- **Suppression:** host tabs (`_isHostTab === true`, based on the `is_host=1` cookie) never see the onboarding. They use `sessionStorage` for identity anyway, so the flag check is explicitly gated by `_isHostTab`.
- **Ordering with loading screen:** the participant page shows a "Connecting…" loading screen (`#loading-screen`) while identity and state are fetched. The onboarding overlay appears **after** that loading screen is hidden, so the participant sees a stable UI underneath the dimmed overlay.
- **Dismissal:** the only way to dismiss is pressing an emoji button in `#emoji-main-bar` or `#emoji-overflow`. No gray-area click, no X button, no timeout. On dismissal, `localStorage['workshop_onboarding_seen'] = '1'` is set; the overlay and tooltip fade out over 300 ms.
- **Persistence:** flag persists across sessions and days on the same browser. Clearing `localStorage` resurrects it (documented as the manual recovery path — no admin control needed).
- **Talk mode:** `talk.html` is served for `session_type == "talk"` and is not touched by this change.

---

## DOM

Two new elements appended at the end of `<body>` in `static/participant.html`:

```html
<div id="onboarding-overlay" class="hidden"></div>
<div id="onboarding-tooltip" class="hidden">
  <div class="onboarding-bubble">
    React as often as you can — tell me how you feel. Tap ☕ when you get tired.
  </div>
  <div class="onboarding-arrow"></div>
</div>
```

No changes to the emoji bar markup itself. The bar is lifted above the overlay via a body-class CSS rule, not by editing its inline classes.

### Z-index stack (only while `body.onboarding-active`)

| Layer | Element | z-index |
|---|---|---|
| Base content | main, sidebar, slides view | default / `z-10` / `z-20` |
| Overlay | `#onboarding-overlay` | 40 |
| Emoji bar wrapper | `.absolute.bottom-6.right-6` (currently `z-30`) | 50 |
| Emoji overflow popup | `#emoji-overflow` | 50 |
| Tooltip bubble | `#onboarding-tooltip` | 51 |

When `onboarding-active` is not set, everything returns to its normal z-index — overlay is hidden, bar stays at `z-30` as today.

---

## Styling

CSS added inline to the existing `<style>` block in `participant.html` (consistent with the file's current pattern):

```css
#onboarding-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 40;
  opacity: 0;
  transition: opacity 300ms ease;
  pointer-events: none; /* forces interaction with the emoji bar */
}
#onboarding-overlay.visible { opacity: 1; }

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

`pointer-events: none` on the overlay is essential: it means clicks on the "dimmed" area pass through to the app — harmless, since the bar is the only lit UI. It also means the only clickable lit region is the emoji bar itself, which is exactly the forced interaction we want.

No coffee-specific pulse or arrow. The tooltip text names `☕` explicitly; that's the only emphasis.

---

## JS

Added near the existing `_isFirstVisit` / UUID setup block in `participant.html`:

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
  overlay.classList.remove('visible');
  tooltip.classList.remove('visible');
  setTimeout(function () {
    overlay.classList.add('hidden');
    tooltip.classList.add('hidden');
    document.body.classList.remove('onboarding-active');
  }, 300);
}
```

### Dismissal wiring — delegated listener

A single delegated `click` listener attached once at init:

```js
document.addEventListener('click', function (e) {
  if (!document.body.classList.contains('onboarding-active')) return;
  var bar = document.getElementById('emoji-main-bar');
  var overflow = document.getElementById('emoji-overflow');
  if ((bar && bar.contains(e.target)) || (overflow && overflow.contains(e.target))) {
    _dismissOnboarding();
  }
}, true); // capture phase so we fire before `sendEmoji` completes
```

This covers every click inside either the main bar or the overflow popup — including emoji promotion clicks (`addEmojiToBar`), direct reactions (`sendEmoji`), and the `+` button. No per-function edits needed, which means the dismissal logic survives future refactors of the bar.

### Debug affordance — reset onboarding flag

The deploy-age line (`#deploy-age-line`, bottom-right corner, shows version + age) currently calls `resetStatePrompt()` which confirms and calls `LS.clear()` (wipes emoji promotions, view prefs, notes/summary unread flags). That's too heavy for testing this feature — the tester wants to see onboarding again without losing avatar, name, promoted emojis, etc.

Rewire the click to a new lightweight handler:

```js
function resetOnboardingForTest() {
  localStorage.removeItem(LS_ONBOARDING_KEY);
  location.reload();
}
```

Wiring changes in the HTML:

```html
<div id="deploy-age-line" onclick="resetOnboardingForTest()" title="Click to reset onboarding (for testing)"
  ...>
```

- No confirm dialog: the action is harmless (one key removed, page reload). Confirm would make testing friction worse.
- The identity UUID, name, avatar, promoted emojis, and view preferences all survive — only the onboarding flag is cleared, so the next page render shows the overlay again.
- For consistency, also add `localStorage.removeItem(LS_ONBOARDING_KEY);` inside `LS.clear()` so if any future flow calls the bulk reset, onboarding resets alongside.
- The old full-state reset path (`resetStatePrompt()` → `LS.clear()`) is kept as a function but loses its only call site. Since it has no other callers today, leaving it unreferenced is acceptable; a future cleanup can remove it. Don't delete it in this change — that's scope creep.

### Entry point — after loading screen hides

The onboarding should fire after the participant state is loaded and the `#loading-screen` overlay is removed. Concrete insertion point: right after `document.getElementById('loading-screen').style.display = 'none';` inside `loadParticipantState()` (currently around line 1664). Add:

```js
if (_shouldShowOnboarding()) _showOnboarding();
```

Single call site — `_shouldShowOnboarding()` gates both first-time and returning participants correctly (returning participants have the flag set and get `false`).

---

## Testing

### Manual (screenshots required per CLAUDE.md)

1. `localStorage.clear()` → reload `/` → verify gray overlay, lit emoji bar, bubble with correct text → screenshot
2. Click any emoji → overlay fades out in ~300 ms, reaction is sent (floating emoji animation plays as normal) → screenshot
3. Reload page → overlay does NOT appear (flag persisted)
4. Click the version line (bottom-right) → no confirm, page reloads, overlay appears again, avatar/name/promoted emojis preserved
5. `localStorage.removeItem('workshop_onboarding_seen')` + reload → overlay appears again (manual path)
6. Host tab (with `is_host=1` cookie) → overlay never appears
7. Talk mode session → `talk.html` served, fully unaffected
8. Dark mode (OS preference) → bubble still legible on lit bar and dim background

### Hermetic (Playwright)

Added to the participant test suite under `tests/` (following existing participant.html patterns; exact location TBD during plan phase):

- New participant (cleared storage) → `#onboarding-overlay.visible` is present after avatar picker closes.
- Click on the first emoji in `#emoji-main-bar` → within 500 ms `#onboarding-overlay` loses the `visible` class, and `localStorage.workshop_onboarding_seen === '1'`.
- Reload within the same session → overlay does not reappear.
- Clicking the overlay area does NOT dismiss (pointer-events: none, click passes through but has no dismissal side effect).

### What's NOT tested

- No visual regression tests for the bubble colors (covered by manual screenshot).
- No test for the avatar-picker → onboarding handoff sequence at the unit level (covered by the E2E scenario).

---

## Out of scope (YAGNI)

- Localization of the tooltip text. It stays in English, consistent with the rest of the participant UI (all emoji titles are English).
- Admin control to reset the flag for all participants. Participants can self-recover via devtools or a fresh browser profile.
- Coffee-specific visual emphasis (pulse, arrow, halo). The tooltip text names `☕` explicitly; that is the only emphasis.
- Backend analytics for onboarding impressions/dismissals. No server-side awareness is needed.
- Feature flag or A/B variant rollout.

---

## Files touched

- `static/participant.html` — add CSS block, HTML elements, JS functions, delegated listener, avatar-picker hook.

No backend changes. No API changes. No new dependencies.
