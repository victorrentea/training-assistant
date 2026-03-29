# Slides Tab + Host Inactivity Auto-Return — Design Spec

**Date:** 2026-03-29

---

## Overview

Two related features:
1. A **Slides tab** added to the host panel as the first (leftmost) tab, giving the host a dedicated button to return participants to slide-browsing mode.
2. A **host inactivity detector** that auto-returns to the Slides tab after 6 minutes of no mouse/keyboard activity on the host page, with a warning overlay after 3 minutes.

---

## Feature 1: Slides Tab

### Tab definition
- **Position:** First tab, leftmost, separated from activity tabs (Poll, Words, Q&A, Code, Debate) by a visual divider.
- **Label:** `Slides`
- **Icon:** 👨🏻‍🏫
- **HTML id:** `tab-slides`
- **`switchTab` argument:** `'none'` (same as the hidden Hello tab — sets `current_activity = NONE` on the backend)

### Behavior on click
1. Calls `switchTab('none')` — sets backend `current_activity` to `NONE`.
2. Backend broadcasts state update to all participants.
3. Participants whose slides were open (or who were following the trainer) return to slide-browsing mode. This is handled by the existing participant-side logic that re-shows the slides panel when `current_activity` becomes `none`.
4. No activity data is deleted — Q&A questions, poll results, word cloud words, etc. are all preserved.

### Tab styling
- Follows the uniform `.tab-btn` class — transparent background, no border, same hover/active states.
- Becomes `.active` when `current_activity === 'none'`.
- The existing hidden `tab-hello` button (👋 Hello) is removed — Slides tab replaces its function.
- Inside `switchTab`, the existing `document.getElementById('tab-hello')` reference must be updated to `tab-slides`.

---

## Feature 2: Host Inactivity Auto-Return

### Scope
- Only active when an activity is running (`current_activity !== 'none'`).
- Tracks **mouse moves**, **clicks**, and **key presses** on the host HTML page (`mousemove`, `click`, `keydown` events on `document`).
- Entirely client-side — no backend involvement.
- **Replaces** the existing 30-second `_autoReturnTimer` / `AUTO_RETURN_DELAY` / `startAutoReturnTimer` / `stopAutoReturnTimer` / `_resetAutoReturn` mechanism entirely. That code must be removed.
- **Mode-agnostic** — applies in both `workshop` and `conference` modes (unlike the old timer which only ran in conference mode).

### Timer logic
| Time | Event |
|------|-------|
| 0 | Activity becomes active; inactivity tracking starts |
| Any mouse/key event | Timer resets to 0 |
| 3 min inactive | Warning modal appears (full-screen, UI-blocking) |
| Any mouse/key event while modal visible | Modal dismissed; **full 6-minute inactivity timer resets** (back to counting from 0) |
| 6 min total inactive (3 min after modal appeared) | `switchTab('none')` called automatically |

### Warning modal
- **Full-screen overlay** over the entire host page (`position: fixed; inset: 0; z-index: 9999`).
- Dark semi-transparent backdrop (`rgba(0,0,0,0.75)`) — host UI visible but blurred/dimmed behind.
- Centered card with amber border, pulsing glow animation.
- Content:
  - Icon: 💤
  - Title: "Are you still there?"
  - Large countdown timer (MM:SS), counting down 3:00 → 0:00
  - Hint: "Move your mouse to stay here"
- **No buttons** — any mouse or keyboard activity dismisses the modal and resets the full inactivity timer back to 3 min.
- When auto-switch fires (countdown reaches 0:00), modal hides and `switchTab('none')` is called.

### Timer reset conditions
- `mousemove` on `document`
- `keydown` on `document`
- Switching to a different activity tab resets and re-arms the timer for the new activity.
- Switching to Slides tab (activity = none) stops tracking entirely.

---

## Files to Change

| File | Change |
|------|--------|
| `static/host.html` | Add Slides tab button (first position), remove `tab-hello` |
| `static/host.js` | Update `switchTab` to handle Slides tab active state; add inactivity tracking module |
| `static/host.css` | Add modal overlay styles (or inline in host.html) |

---

## Non-Goals
- No backend changes required.
- No participant-side changes required (existing `current_activity = none` handling is sufficient).
- No persistence of inactivity state across page reloads.
- Does not affect conference mode or leaderboard behavior.
