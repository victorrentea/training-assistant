# Hello Tab (Conference Mode)

## Summary

Add a 👋 tab as the first tab in the host tab bar, visible only in conference mode. Clicking it sets `current_activity` to `"none"`, which shows the emoji reaction grid on participant screens. An auto-return timer (30s of host inactivity) automatically switches back to the 👋 tab in conference mode.

## Requirements

1. **👋 tab in host tab bar** — first position, visible only in conference mode
2. **Click behavior** — sends `activity: "none"` to server via existing `/api/activity` endpoint
3. **Active state** — tab appears selected when `current_activity === "none"`
4. **Auto-return timer (conference mode only)**:
   - Resets on any `click`, `keypress`, `mousemove` on the host page
   - After 30s of inactivity, auto-switches to 👋 (sets activity to `"none"`)
   - Only active when `current_activity !== "none"`
   - Disabled entirely in workshop mode

## Scope

- **Files changed**: `static/host.html`, `static/host.js`
- **No backend changes** — uses existing `/api/activity` endpoint with `{"activity": "none"}`
- **No participant changes** — participant already shows emoji grid when activity is `"none"` in conference mode

## Tab bar layout

- **Workshop**: 📊 ☁ ❓ 🕵️ ⚔️ 🏆
- **Conference**: 👋 📊 ☁ ❓ 🕵️ 🏆

## Implementation notes

- Tab visibility toggled via `conferenceMode` flag (same pattern as Debate tab)
- Auto-return timer: single `setTimeout` reference, cleared and reset on each user interaction event
- Event listeners for auto-return added/removed when mode changes
