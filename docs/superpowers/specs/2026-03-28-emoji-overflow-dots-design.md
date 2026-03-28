# Emoji Bar Overflow Design

**Date:** 2026-03-28
**Status:** Approved

## Summary

Replace the fixed 14-emoji bar with a responsive, priority-driven bar that shows as many emojis as fit in the available width. Overflow emojis go into a vertical popup triggered by a ••• button. Usage-based reordering promotes frequently-used emojis into the visible strip.

---

## Changes to Emoji List

**Removed:** 🎉 (confetti), 👏 (clapping/standing ovation)

**Always-visible (never overflow):** •••, 🖥️ (ping), 📤 (upload), 📋 (paste)

**11 overflow-eligible emojis in initial priority order:**

| Priority | Emoji | Tooltip |
|---|---|---|
| 1 | ❤️ | Genuinely love this. |
| 2 | ☕ | I need a break. Now. |
| 3 | 👍 | Yes. More of this. |
| 4 | 🔥 | This is absolute fire. |
| 5 | 🤔 | Hmm... not convinced yet. |
| 6 | ⚔️ | Fight me on this. |
| 7 | 😂 | I'm dead 💀 |
| 8 | 🤯 | My brain just exploded. |
| 9 | 💡 | Wait, I have an idea! |
| 10 | ✅ | Agreed. 100%. |
| 11 | ❌ | Nope. Hard disagree. |

🖥️ is **not** in the overflow pool — it is always-visible (fixed position after •••).

---

## Layout

Bottom bar order (left to right):
```
[visible emojis...] [•••] [🖥️] | [📤] [📋]
```

- Upload and paste are separated from the rest by a vertical divider line
- ••• and 🖥️ are always visible regardless of screen width
- Visible emoji count = however many fit in remaining space (min 0, up to all 11 non-🖥️ emojis)

---

## Responsive Fitting Logic

On mount and on every `resize` event:
1. Measure available width = bar width − (width of •••) − (width of 🖥️) − (width of upload+paste+divider) − gaps
2. Each emoji button is 40px + 8px gap = 48px
3. Visible count = `Math.floor(availableWidth / 48)`, capped at 11 (all overflow-eligible emojis)
4. Show top-N emojis from priority list; remainder go into popup
5. If N ≥ 11 (all fit): hide ••• button; 🖥️ still visible
6. On resize while popup is open: close popup, then re-layout
7. Tapping a visible emoji never opens/closes the popup; popup state is unchanged

---

## Priority / Reordering

- `localStorage` key: `emoji_use_counts` — JSON object mapping emoji → integer count
- On each emoji tap (visible or popup): increment its count, re-sort, re-render bar
- Sort: descending by count, ties broken by initial priority order
- After re-sort, re-apply the fitting logic to determine visible vs popup

---

## ••• Popup

- Appears above the ••• button, vertically stacked
- Contains all emojis NOT currently in the visible strip (excluding 🖥️ which is always visible)
- Small ✕ button in top-right corner of popup (18px, ~50% of emoji button size) to close it
- Clicking an emoji from the popup: fires the emoji, increments its count, closes popup, re-sorts
- Clicking outside popup (document click) also closes it
- Popup scrolls if it would exceed viewport height

---

## Onboarding Tour

The onboarding tour currently selects 4 random emoji buttons. Update selector logic to only pick from buttons present in `#emoji-bar` at tour time (still works — just fewer candidates).

---

## Out of Scope

- Conference mode emoji grid — unchanged
- Host panel — unchanged
- Emoji animation effects — unchanged
