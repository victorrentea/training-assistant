# Participant Content Zoom — Design

**Date:** 2026-05-22
**Status:** Approved (pending implementation plan)

## Goal

Let participants enlarge or shrink the text in the three reading-heavy views — **Notes**, **AI Summary**, and **Agenda** — using **Ctrl + mouse wheel** (or trackpad pinch on macOS, which emits the same event). The left navigation bar, top header, badges, and other views are unaffected.

## Scope

**Affected views (right pane only):**

- `#notes-view` → `#notes-content`
- `#summary-view` → `#summary-content`
- `#agenda-view` → `#agenda-content`

**Out of scope:**

- All other participant views (activity, slides, feedback, upload-paste, landing)
- Host page
- Keyboard shortcuts (`Ctrl+=` / `Ctrl+-` / `Ctrl+0`) — explicitly excluded per the user
- UI controls (no zoom buttons, no slider, no menu entry)

## Behavior

| Aspect | Value |
|---|---|
| Trigger | `wheel` event with `event.ctrlKey === true` (also matches macOS trackpad pinch) |
| Step | ±10 % per wheel notch (`deltaY < 0` zooms in, `deltaY > 0` zooms out) |
| Range | 50 % – 300 % (clamped) |
| Default | 100 % |
| Persistence | Global, shared across all three views, persisted in `localStorage` |
| Scope of listener | Attached on the three view containers only — `Ctrl+wheel` over the nav, header, or other views does **not** trigger custom zoom |
| Browser-native zoom | Always suppressed (`preventDefault()`) while the wheel event occurs inside one of the three views, including at min/max boundary, so participants never get the browser's own zoom mixed in |

The zoom factor is a single number `Z ∈ {0.5, 0.6, …, 3.0}`. Rounded to one decimal after each step to avoid floating-point drift.

## Implementation

### 1. CSS

Add a CSS custom property on `:root` with default `1`, and move the existing inline `font-size: 120%` declarations off `#summary-view` and `#agenda-view` into CSS rules that multiply by the variable.

```css
:root {
  --participant-zoom: 1;
}

#notes-content {
  font-size: calc(1rem * var(--participant-zoom));
}

#summary-content {
  font-size: calc(1.2rem * var(--participant-zoom));
}

#agenda-content {
  font-size: calc(1.2rem * var(--participant-zoom));
}
```

The intrinsic baseline per view stays the same as today: notes at 100 %, summary and agenda at 120 %. The multiplier scales them together so a user who zooms to 150 % sees notes at 150 % and summary/agenda at 180 % — preserving the current visual ratio.

Remove only the `font-size: 120%` declaration from the inline `style` attribute on `#summary-view` and `#agenda-view` (leaving other declarations like `display:none` intact) so the new CSS rules are not overridden.

### 2. JavaScript

In `static/participant.html` (where the other view-level scripts live), add:

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

Call `_installContentZoom()` once during the existing participant bootstrap (alongside the other DOM-ready setup).

`{ passive: false }` is required because we need `preventDefault()` to actually suppress browser zoom.

### 3. No other state

The zoom value is read from `localStorage` at boot and lives only in the CSS variable thereafter. No daemon sync, no WS message, no host visibility — purely local to each participant's browser.

## What does not change

- Scroll position save/restore (`saveScroll('notes', el)` etc.) continues to work — only `font-size` changes, the scroll container element is unchanged
- The `prose max-w-none` typography and the `whitespace-pre-wrap` behavior of notes
- Badges, nav-item sizing, and the right-pane action buttons (download, etc.) — they live outside the `*-content` element
- The 120 % baseline for summary/agenda at zoom = 1.0 (moved from inline to CSS, identical computed value)

## Risk and edge cases

| Risk | Mitigation |
|---|---|
| Existing inline `style="font-size:120%"` overrides the CSS rule | Remove the inline attribute on `#summary-view` and `#agenda-view` |
| `wheel` event arrives before zoom is initialized | `_loadContentZoom()` runs synchronously in `_installContentZoom()` before listeners are bound |
| Floating-point drift after many wheel ticks | `Math.round(z * 10) / 10` after every step |
| Trackpad pinch on macOS sends very small `deltaY` values | Step is fixed at ±10 % per event regardless of magnitude — predictable feel, matches browser behavior |
| Listener swallows scroll if user accidentally holds Ctrl while scrolling | This is the desired behavior — without Ctrl, the wheel scrolls the content as today |

## Testing

Manual verification on the participant page in local dev (`http://localhost:8081/`) plus a hermetic Playwright check is overkill for a pure-UI keyboard interaction. Manual test plan:

1. Open participant view, switch to Notes.
2. Ctrl + wheel up — text grows by 10 %.
3. Ctrl + wheel up repeatedly until clamped at 300 %.
4. Ctrl + wheel down to 50 %, confirm clamp.
5. Reload — zoom persists.
6. Switch to Summary — same zoom factor visible (baseline is 120 % × Z).
7. Switch to Agenda — same zoom factor visible.
8. Switch to Activity / Slides / Feedback — unaffected.
9. Ctrl + wheel over the left nav — browser default behavior (no custom zoom triggered).
10. Plain wheel (no Ctrl) — scrolls content as before.

## Files touched

- `static/participant.html` — add CSS rules, JS functions, install hook; remove inline `font-size:120%` from `#summary-view` and `#agenda-view`
