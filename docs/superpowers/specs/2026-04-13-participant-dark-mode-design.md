# Participant Page Dark Mode — Design Spec

**Date:** 2026-04-13  
**Goal:** Add OS-synced dark mode to the new `static/participant.html` using `@media (prefers-color-scheme: dark)`.

---

## Context

The new participant page uses a custom Tailwind CSS build (`static/vendor/tailwind.css`) with Material Design 3 (MD3)-inspired color tokens baked in as **hardcoded light-mode RGB values**. There is no CSS variable system or dark mode infrastructure.

Current color token Tailwind classes (all light-only):
- `.bg-surface` → `rgb(247 249 251)`
- `.bg-surface-container` → `rgb(232 239 243)`
- `.bg-surface-container-high` → `rgb(225 233 238)`
- `.bg-surface-container-highest` → `rgb(217 228 234)`
- `.bg-surface-container-low` → `rgb(240 244 247)`
- `.bg-primary` → `rgb(69 85 186)`
- `.bg-primary-container` → `rgb(223 224 255)`
- `.text-on-surface` → `rgb(42 52 57)`
- `.text-on-surface-variant` → `rgb(86 97 102)`
- `.text-primary` → `rgb(69 85 186)`
- `.text-on-primary` → `rgb(249 246 255)`
- `.text-on-primary-container` → `rgb(55 71 172)`
- `.border-primary` → `rgb(69 85 186)`
- `.border-outline-variant` → `rgb(169 180 185)`

Additionally, several components use hardcoded light-mode colors in inline styles or embedded CSS:
- `.glass` → `background: rgba(247, 249, 251, 0.8)`
- `.whisper-shadow` → `box-shadow: 0px 12px 32px rgba(42, 52, 57, 0.06)`
- `#emoji-main-bar` inline → `background:rgba(247,249,251,0.4);border:1.5px solid rgba(150,160,165,0.6)`
- `#emoji-overflow` inner div inline → same rgba values
- Scrollbar thumb → `#d9e4ea` and `#a9b4b9`

---

## Approach

### New file: `static/participant-theme.css`

Loaded after `tailwind.css` in `participant.html`. Contains:

**1. CSS custom properties (`:root`) for all MD3 color tokens — light palette**

Defines `--color-*` variables that inline `var(--color-primary, #fallback)` references in the HTML will use.

**2. `@media (prefers-color-scheme: dark)` block — dark palette**

Redefines all `--color-*` variables for dark mode.

**3. Tailwind class overrides — dark mode only**

Since `participant-theme.css` loads after `tailwind.css`, equal-specificity rules in `participant-theme.css` win for dark mode. No `!important` needed.

**4. Component dark overrides** (`.glass`, `.whisper-shadow`, scrollbar)

Override inside `@media (prefers-color-scheme: dark)`.

**5. Inline style overrides via CSS classes**

`#emoji-main-bar` and `#emoji-overflow`'s inner div currently use hardcoded inline rgba colors. Since inline styles can't be overridden by a stylesheet, replace those inline `style="..."` attributes with a CSS class `.emoji-bar-surface` defined in `participant-theme.css`.

---

## Color Palette

### Light (current — already in tailwind.css)
| Token | RGB |
|---|---|
| primary | 69 85 186 |
| primary-container | 223 224 255 |
| on-primary | 249 246 255 |
| on-primary-container | 55 71 172 |
| surface | 247 249 251 |
| surface-container-low | 240 244 247 |
| surface-container | 232 239 243 |
| surface-container-high | 225 233 238 |
| surface-container-highest | 217 228 234 |
| on-surface | 42 52 57 |
| on-surface-variant | 86 97 102 |
| outline-variant | 169 180 185 |

### Dark (new — MD3 standard dark tone mapping for blue/indigo hue)
| Token | RGB |
|---|---|
| primary | 188 196 255 |
| primary-container | 39 54 154 |
| on-primary | 17 35 120 |
| on-primary-container | 223 224 255 |
| surface | 18 21 26 |
| surface-container-low | 22 27 32 |
| surface-container | 28 33 38 |
| surface-container-high | 38 43 49 |
| surface-container-highest | 48 54 60 |
| on-surface | 220 228 233 |
| on-surface-variant | 169 180 185 |
| outline-variant | 60 72 77 |

---

## Changes to `participant.html`

1. **Add link to `participant-theme.css`** after the tailwind.css link.
2. **Remove `class="light"` from `<html>`** — no longer needed.
3. **Add tiny JS snippet** (in `<head>` before font load) to sync `html.dark`/`html.light` with OS preference and listen for changes. This keeps future JS code that might check the class working correctly.
4. **Replace inline `style=` on `#emoji-main-bar`** with class `emoji-bar-surface`.
5. **Replace inline `style=` on the inner div of `#emoji-overflow`** with class `emoji-bar-surface`.

---

## Files Changed

| File | Change |
|---|---|
| `static/participant-theme.css` | **New** — CSS variables + dark mode overrides |
| `static/participant.html` | Link theme CSS, remove `class="light"`, add OS-sync JS, swap two inline styles for class |

---

## Out of Scope

- No manual theme toggle (pure OS preference sync)
- No changes to `static/vendor/tailwind.css`
- No changes to `static/common.css` (old participant page)
- Avatar modal borders (`#fff`) left as-is (visually acceptable in dark mode)
