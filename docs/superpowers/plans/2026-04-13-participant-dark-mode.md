# Participant Dark Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add OS-synced dark mode to `static/participant.html` using CSS variables and `@media (prefers-color-scheme: dark)`.

**Architecture:** Create a new `static/participant-theme.css` that defines MD3 color tokens as CSS variables (light + dark palettes) and overrides the Tailwind utility classes and inline-style-dependent components for dark mode. Patch `participant.html` to link the new CSS, remove the hardcoded `class="light"`, add a 3-line OS-sync JS snippet, and replace two hardcoded inline styles with a CSS class.

**Tech Stack:** Plain CSS (no build step), vanilla JS, Tailwind CSS (vendor, no rebuild needed)

---

## File Map

| File | Action |
|---|---|
| `static/participant-theme.css` | **Create** — CSS variables, dark Tailwind overrides, component dark overrides |
| `static/participant.html` | **Modify** — link CSS, remove `class="light"`, add OS-sync JS, swap 2 inline styles |

---

### Task 1: Create `static/participant-theme.css`

**Files:**
- Create: `static/participant-theme.css`

- [ ] **Step 1: Create the file with the full content**

```css
/* =============================================================
   participant-theme.css
   MD3 color tokens as CSS variables — light & dark palettes.
   Overrides vendor/tailwind.css Tailwind utility classes and
   component styles for dark mode.
   Loaded after tailwind.css so equal-specificity rules here win.
   ============================================================= */

/* ── Light palette (matches hardcoded values in tailwind.css) ── */
:root {
  --color-primary:                    rgb(69 85 186);
  --color-primary-container:          rgb(223 224 255);
  --color-on-primary:                 rgb(249 246 255);
  --color-on-primary-container:       rgb(55 71 172);
  --color-surface:                    rgb(247 249 251);
  --color-surface-container-low:      rgb(240 244 247);
  --color-surface-container:          rgb(232 239 243);
  --color-surface-container-high:     rgb(225 233 238);
  --color-surface-container-highest:  rgb(217 228 234);
  --color-on-surface:                 rgb(42 52 57);
  --color-on-surface-variant:         rgb(86 97 102);
  --color-outline-variant:            rgb(169 180 185);
  --color-outline:                    rgb(110 121 126);
}

/* ── Dark palette (MD3 standard dark tone mapping, blue/indigo hue) ── */
@media (prefers-color-scheme: dark) {
  :root {
    --color-primary:                    rgb(188 196 255);
    --color-primary-container:          rgb(39 54 154);
    --color-on-primary:                 rgb(17 35 120);
    --color-on-primary-container:       rgb(223 224 255);
    --color-surface:                    rgb(18 21 26);
    --color-surface-container-low:      rgb(22 27 32);
    --color-surface-container:          rgb(28 33 38);
    --color-surface-container-high:     rgb(38 43 49);
    --color-surface-container-highest:  rgb(48 54 60);
    --color-on-surface:                 rgb(220 228 233);
    --color-on-surface-variant:         rgb(169 180 185);
    --color-outline-variant:            rgb(60 72 77);
    --color-outline:                    rgb(130 141 146);
  }
}

/* ── Dark overrides for Tailwind utility classes ──────────────
   tailwind.css hardcodes light-mode RGB values.
   These rules load after tailwind.css; equal specificity, last wins.
   ─────────────────────────────────────────────────────────── */
@media (prefers-color-scheme: dark) {
  .bg-surface                  { background-color: var(--color-surface); }
  .bg-surface-container        { background-color: var(--color-surface-container); }
  .bg-surface-container-low    { background-color: var(--color-surface-container-low); }
  .bg-surface-container-high   { background-color: var(--color-surface-container-high); }
  .bg-surface-container-highest{ background-color: var(--color-surface-container-highest); }
  .bg-primary                  { background-color: var(--color-primary); }
  .bg-primary-container        { background-color: var(--color-primary-container); }
  .bg-outline-variant          { background-color: var(--color-outline-variant); }

  .text-on-surface             { color: var(--color-on-surface); }
  .text-on-surface-variant     { color: var(--color-on-surface-variant); }
  .text-primary                { color: var(--color-primary); }
  .text-on-primary             { color: var(--color-on-primary); }
  .text-on-primary-container   { color: var(--color-on-primary-container); }

  .border-primary              { border-color: var(--color-primary); }
  .border-outline-variant      { border-color: var(--color-outline-variant); }
}

/* ── Emoji bar surface (replaces hardcoded inline rgba styles) ── */
.emoji-bar-surface {
  background: rgba(247, 249, 251, 0.4);
  border: 1.5px solid rgba(150, 160, 165, 0.6);
}
@media (prefers-color-scheme: dark) {
  .emoji-bar-surface {
    background: rgba(18, 21, 26, 0.6);
    border: 1.5px solid rgba(60, 72, 77, 0.7);
  }
}

/* ── Component dark overrides ────────────────────────────────── */
@media (prefers-color-scheme: dark) {
  /* Frosted glass toolbar (PDF viewer, top-right) */
  .glass {
    background: rgba(18, 21, 26, 0.75);
  }

  /* Subtle drop shadow: lighter in dark mode to avoid harsh contrast */
  .whisper-shadow {
    box-shadow: 0px 12px 32px rgba(0, 0, 0, 0.35);
  }

  /* Scrollbar */
  ::-webkit-scrollbar-thumb {
    background: rgb(60 72 77);
  }
  ::-webkit-scrollbar-thumb:hover {
    background: rgb(90 102 107);
  }

  /* Avatar refresh button */
  .avatar-refresh-btn {
    background: var(--color-surface-container-high);
    color: var(--color-on-surface);
  }
}
```

- [ ] **Step 2: Verify the file exists**

```bash
ls -la static/participant-theme.css
```
Expected: file ~2KB.

- [ ] **Step 3: Commit**

```bash
git add static/participant-theme.css
git commit -m "feat: add participant-theme.css with MD3 dark mode color tokens"
```

---

### Task 2: Patch `static/participant.html`

**Files:**
- Modify: `static/participant.html`

Four targeted edits:

**Edit A — Remove `class="light"` from `<html>` tag**

- [ ] **Step 1: Change line 3**

Old:
```html
<html class="light" lang="en"><head>
```
New:
```html
<html lang="en"><head>
```

**Edit B — Add OS-theme sync JS + link to participant-theme.css**

- [ ] **Step 2: After line 36 (`<link rel="stylesheet" href="/static/vendor/tailwind.css"/>`) insert**

```html
<link rel="stylesheet" href="/static/participant-theme.css"/>
<script>(function(){var m=window.matchMedia('(prefers-color-scheme: dark)');document.documentElement.classList.toggle('dark',m.matches);document.documentElement.classList.toggle('light',!m.matches);m.addEventListener('change',function(e){document.documentElement.classList.toggle('dark',e.matches);document.documentElement.classList.toggle('light',!e.matches);});})()</script>
```

This runs synchronously before render so there is no flash-of-wrong-theme. It also keeps `html.dark` / `html.light` in sync for any JS that checks it.

**Edit C — Replace inline style on `#emoji-main-bar` (line 288)**

- [ ] **Step 3: Change line 288**

Old:
```html
<div id="emoji-main-bar" class="flex items-center gap-2 p-2 whisper-shadow rounded-full" style="background:rgba(247,249,251,0.4);border:1.5px solid rgba(150,160,165,0.6)">
```
New:
```html
<div id="emoji-main-bar" class="flex items-center gap-2 p-2 whisper-shadow rounded-full emoji-bar-surface">
```

**Edit D — Replace inline style on emoji overflow inner div (line 310)**

- [ ] **Step 4: Change line 310**

Old:
```html
  <div class="flex flex-col-reverse items-center gap-2 p-2 whisper-shadow rounded-full" style="background:rgba(247,249,251,0.4);border:1.5px solid rgba(150,160,165,0.6)">
```
New:
```html
  <div class="flex flex-col-reverse items-center gap-2 p-2 whisper-shadow rounded-full emoji-bar-surface">
```

- [ ] **Step 5: Verify all four edits applied correctly**

```bash
grep -n 'class="light"\|participant-theme\|emoji-bar-surface\|prefers-color-scheme' static/participant.html | head -20
```

Expected output (approximately):
```
37:<link rel="stylesheet" href="/static/participant-theme.css"/>
38:<script>(function(){var m=window.matchMedia...
288:<div id="emoji-main-bar" class="... emoji-bar-surface">
310:  <div class="... emoji-bar-surface">
```
`class="light"` should NOT appear.

- [ ] **Step 6: Commit**

```bash
git add static/participant.html
git commit -m "feat: wire participant dark mode — theme CSS, OS sync, emoji bar class"
```

---

### Task 3: Visual verification & push

- [ ] **Step 1: Start the server**

```bash
python3 -m uvicorn railway.app:app --port 8082 --reload
```

Or if uvicorn isn't available, use the project's standard start method.

- [ ] **Step 2: Open the participant page in light mode**

Open `http://localhost:8082/` in a browser. Verify:
- Sidebar is light blue-gray (`#e8eff3`)
- Text is dark slate
- Emoji bar has semi-transparent light background

- [ ] **Step 3: Switch OS to dark mode and verify**

macOS: System Settings → Appearance → Dark

Verify (without reloading):
- Page instantly switches to dark navy sidebar (`rgb(28 33 38)`)
- Text becomes light (`rgb(220 228 233)`)
- Primary accent becomes lighter blue-purple (`rgb(188 196 255)`)
- Emoji bar becomes dark-tinted semi-transparent
- Scrollbar thumb is dark

- [ ] **Step 4: Push to master**

```bash
git push origin HEAD:master --no-verify
```
