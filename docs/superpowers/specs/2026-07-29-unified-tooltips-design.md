# Unified Tooltip Component — Design

**Date:** 2026-07-29
**Status:** Approved for implementation
**Scope:** New shared frontend component, migration of every tooltip on every surface, an anti-drift test, a personal skill

## Motivation

Tooltips in this app are inconsistent because there is no component to be consistent with. Three systems exist:

| System | Live usages | Style | Delay |
|---|---|---|---|
| Native `title=` | **38** — `participant.html` 12, `host.html` 11, `host.js` 14, `notes.html` 1 | browser default, ~11–13px, unstyleable | ~500ms |
| `#emoji-tooltip` + `data-tip` | **2** — `participant.html`, and only inside `#floating-reactions` | dark opaque, 1.25rem, peek-in | 150ms |
| `.has-tooltip` + `data-tooltip` | **0** | `--surface2` + border, 0.78rem, arrow | 400ms |

The third is **dead code**: `common.css:73-125` and `host.css:374-375` carry styles no markup applies. It gets deleted, not migrated.

The second is the one to keep — it is bigger, three times faster, and its peek-in (`translateY(4px) → 0` alongside the opacity fade, 120ms) is what makes it feel alive rather than merely appearing. Its flaw is reach: the listeners are bound to `#floating-reactions`, so `data-tip` anywhere else silently does nothing. That is why only two elements use it.

The drift is active, not historical: the download glyph shipped earlier today used a native `title=`. Without a component and a guard, the next one will too.

## Goals

1. One tooltip implementation, one visual identity, on every surface.
2. `data-tip` works on any element on any page — no host container to register with.
3. A test that fails when someone reintroduces a native `title=`.
4. The download glyph in the Google Drive row reads as a button, not an ornament.
5. A reusable skill capturing the convention.

## Non-goals

- **Responsive / mobile tuning.** `interact` is not responsive yet and mobile rendering has not been studied; explicitly out of scope. One size (`1.25rem`) everywhere, desktop-first.
- Theming the tooltip per light/dark. It is deliberately dark in both, as tooltips commonly are.
- Rich content (HTML, images) inside tooltips. Text only.
- Replacing the onboarding bubbles (`#onboarding-tooltip-2`, `#break-reminder-tooltip`). Those are guided-tour popovers with their own lifecycle and dismissal, not hover hints — a different component that happens to share the word "tooltip".

## A. The component

**`static/tooltip.js`** — one file that injects its own stylesheet on load.

The project has no build step, so the alternative would be a `.js` plus a `.css` that every page must remember to include together. Bundling the style into the script makes a page's adoption a single line and makes it impossible to get the behavior without the look.

Loaded by: `participant.html`, `host.html`, `landing.html`, `notes.html`, `talk.html`, `host-landing.html`.

### API

```html
<button data-tip="Download everything as .zip">…</button>
```

Nothing to initialize. Listeners are delegated on `document`, so markup injected later (host.js renders most of its UI from template strings) works with no registration step.

### Visual tokens

Lifted verbatim from `#emoji-tooltip` so nothing about the look changes where it is already liked:

| Token | Value |
|---|---|
| background | `rgba(20, 20, 22, 0.96)` |
| color | `#fff` |
| font | `1.25rem` / weight `600` / line-height `1.25` |
| padding | `0.6rem 0.9rem` |
| border-radius | `0.6rem` |
| max-width | `22rem` (wraps; never `nowrap`) |
| box-shadow | `0 10px 30px rgba(0, 0, 0, 0.35)` |
| transition | `opacity 120ms ease, transform 120ms ease` |
| peek-in | `opacity 0→1`, `translateY(4px)→0` |
| hover delay | `150ms` |
| z-index | `60` |

### Positioning

Single `<div>` appended to `<body>`, `position: fixed`, `pointer-events: none`. Placed above the trigger; flipped below when there is no room; clamped to 8px from the viewport edges. Identical to the current emoji logic.

### Behavior added for general use

The emoji version is a hover-only widget on one bar. As a shared component it needs four more things:

- **Keyboard**: show on `focus`, hide on `blur` and on `Escape`.
- **Accessibility**: set `aria-label` from `data-tip` only when the element has no accessible name already (text content, `aria-label`, or `aria-labelledby`). Blindly overwriting would degrade buttons that already read correctly.
- **Scroll**: hide on `scroll`. The current implementation computes position once; a fixed-position bubble left behind during a scroll floats detached from its trigger.
- **Touch**: hide on `touchstart`. Mobile is out of scope, but a tooltip that sticks after a tap is a bug worth not introducing.

Empty or absent `data-tip` shows nothing — several call sites are conditional (`host.js:1488` renders `title="${ip ? 'IP: ' + ip : ''}"`).

## B. Migration

All 38 native `title=` become `data-tip`. There are **no legitimate exceptions to allow-list**: the `<title>` tags in each page's `<head>` are elements, not attributes, so the guard's `title="` pattern does not match them.

Cases needing care:

- `participant.html:823` carries two `title=` attributes on one line; `host.js:1474` carries three. A naive line-based replace would miss the later ones.
- Dynamic values inside template strings (`host.js:167`, `1481`, `1486`, `1488`; `participant.html:4944`, `5079`) keep their interpolation: `data-tip="${escAttr(...)}"`.
- `host.html:263` is an `<svg>` used as a clickable icon — it migrates like any other interactive element.

Deletions:

- `participant.html`: the local `#emoji-tooltip` CSS block (lines ~213–234) and its JS (`_emojiTipEl`, `_showEmojiTip`, `_hideEmojiTip`, `_wireEmojiTips`, ~lines 2461–2513). `applyEmojiTip` keeps its name and callers but reduces to setting `data-tip` + `aria-label`.
- `common.css:73-125` and `host.css:374-375`: the dead `.has-tooltip` rules.

## C. Anti-drift guard

A test asserting no `title="` attribute exists in `static/**/*.{html,js}`.

Without it the component is a convention, and this codebase has already demonstrated how conventions here erode — three systems accumulated, and a fourth native `title=` was added earlier today by the same person writing this spec.

Failure message names the offending file, line, and the fix (`use data-tip instead`).

## D. Download glyph highlight

The glyph is `opacity: 0.6` with no background, sitting next to a purely decorative `open_in_new` icon. It reads as ornament.

- Permanent subtle background (a circular `bg-surface-container`-equivalent) so it is legible as a control at a glance.
- Hover intensifies it, matching the surrounding nav rows' `hover:bg-surface-container`.
- `data-tip="Download everything as .zip"` replaces the native `title=`.

## E. Menu label

The participant sidebar entry `Files` becomes `Opened Files`, matching the `opened-files.md` artifact renamed in `b26363bf` and the section heading the file itself already carries ("Files opened this session").

## F. The skill

`~/workspace/ai/skills/tooltips/SKILL.md`, committed and pushed to `victorrentea/ai` per the personal-skills convention.

Written as general guidance rather than tied to this repo's paths, so it applies to other projects: one component per app, a declarative attribute, never a native `title`, the exact visual tokens above, and the peek-in as the signature that separates a tooltip that feels responsive from one that merely appears.

## Testing

- **Guard test**: no `title="` in `static/`.
- **Component tests** (Playwright, alongside the existing frontend tests): tooltip appears after the delay on hover, carries the expected text, disappears on mouseout, flips below the trigger when there is no room above, and appears on keyboard focus.
- **Visual proof**: screenshot of a host-panel tooltip and a participant tooltip side by side, showing one identity.

## Deployment

`static/**` only — ships automatically on push via the daemon's `static_sync`, with no Railway redeploy.
