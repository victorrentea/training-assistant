# Participant Onboarding Tour Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a one-shot guided tour to first-time participants, with a floating bubble per UI element, plus a hidden dev-reset gesture on the version tag.

**Architecture:** Tour runs entirely in the browser (vanilla JS). First-visit detection uses localStorage flag `workshop_tour_shown`. A sequential bubble engine highlights one element at a time (4 emoji + location + key points + name), advances on tap, and can be skipped. The dev-reset is a click handler on the existing `#version-tag` element, hidden from participants by design.

**Tech Stack:** Vanilla JS (ES6), plain CSS, no dependencies

---

## File Map

| File | Change |
|------|--------|
| `static/participant.html` | Replace `👎` with `⚔️` in `#emoji-bar` |
| `static/participant.js` | Add `runOnboardingTourIfNeeded()` + dev-reset handler |
| `static/participant.css` | Add `.tour-bubble`, `.tour-glow`, `.tour-dots` styles |

---

### Task 1: Replace 👎 with ⚔️ in the emoji bar

**Files:**
- Modify: `static/participant.html:84`

- [ ] **Step 1: Edit the emoji bar**

In `static/participant.html`, find:
```html
<button class="emoji-btn" onclick="sendEmoji('👎', event)">👎</button>
```
Replace with:
```html
<button class="emoji-btn" onclick="sendEmoji('⚔️', event)">⚔️</button>
```

- [ ] **Step 2: Verify locally** — open `http://localhost:8000/` and confirm 👎 is gone, ⚔️ is there

- [ ] **Step 3: Commit**
```bash
git add static/participant.html
git commit -m "feat(participant): replace 👎 with ⚔️ in emoji bar"
```

---

### Task 2: Add onboarding tour CSS

**Files:**
- Modify: `static/participant.css` (append at end)

- [ ] **Step 1: Append tour styles**

```css
/* ── Onboarding tour ── */
.tour-bubble {
  position: fixed;
  background: rgba(20, 20, 35, 0.97);
  border: 1px solid var(--accent);
  border-radius: 14px;
  padding: 12px 16px;
  max-width: 240px;
  font-size: .88rem;
  color: var(--text);
  line-height: 1.45;
  z-index: 9000;
  pointer-events: auto;
  box-shadow: 0 8px 32px rgba(0,0,0,.6);
  animation: tour-bubble-in .25s ease-out;
}
@keyframes tour-bubble-in {
  from { opacity: 0; transform: translateY(8px) scale(.96); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}
.tour-bubble::after {
  content: '';
  position: absolute;
  width: 10px;
  height: 10px;
  background: rgba(20, 20, 35, 0.97);
  border-right: 1px solid var(--accent);
  border-bottom: 1px solid var(--accent);
  transform: rotate(45deg);
  bottom: -6px;
  left: 50%;
  margin-left: -5px;
}
.tour-bubble.arrow-top::after {
  bottom: auto;
  top: -6px;
  border-right: none;
  border-bottom: none;
  border-left: 1px solid var(--accent);
  border-top: 1px solid var(--accent);
}
.tour-bubble-emoji {
  font-size: 1.5rem;
  display: block;
  margin-bottom: 4px;
}
.tour-bubble-text {
  display: block;
  margin-bottom: 8px;
}
.tour-bubble-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 4px;
}
.tour-dots {
  display: flex;
  gap: 5px;
  align-items: center;
}
.tour-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--border);
  transition: background .2s;
}
.tour-dot.active {
  background: var(--accent);
}
.tour-skip {
  background: none;
  border: none;
  color: var(--muted);
  font-size: .75rem;
  cursor: pointer;
  padding: 2px 4px;
  opacity: .7;
}
.tour-skip:hover { opacity: 1; }
.tour-tap-hint {
  font-size: .72rem;
  color: var(--muted);
  opacity: .8;
}
.tour-glow {
  box-shadow: 0 0 0 3px var(--accent), 0 0 12px 2px rgba(99,102,241,.5) !important;
  border-color: var(--accent) !important;
  transition: box-shadow .3s, border-color .3s;
}
/* Dev-reset cursor on version tag */
#version-tag:hover {
  color: var(--text) !important;
  cursor: pointer;
  opacity: 1;
}
```

- [ ] **Step 2: Commit**
```bash
git add static/participant.css
git commit -m "feat(participant): add onboarding tour CSS"
```

---

### Task 3: Implement the tour engine in participant.js

**Files:**
- Modify: `static/participant.js`

The tour is a self-contained IIFE-style function. Insert it after the global constants (after line ~80, before `escHtml`).

**First-visit detection:** `getOrCreateUUID()` already creates UUID and saves to `uuidStorage`. We detect first visit **before** that save happens — check if `uuidStorage.getItem(LS_UUID_KEY)` is null, then let `getOrCreateUUID()` run normally, and set `_isFirstVisit = true`.

**Steps (7 total):**
```
0: ☕  → anchor: button[onclick*="☕"]  bubble below bar  "God, I need a coffee ☕ — tap this when you're running on fumes and need a break. No shame."
1: 👍  → anchor: button[onclick*="👍"]  bubble below bar  "Tap 👍 when the speaker says something brilliant. Their ego needs the fuel."
2: ⚔️  → anchor: button[onclick*="⚔️"]  bubble below bar  "⚔️ Disagreement battle mode! Fight me on this — intellectually speaking. Tap when you strongly disagree."
3: 🔥  → anchor: button[onclick*="🔥"]  bubble below bar  "🔥 This. Is. Fire. Tap when the content is genuinely mind-blowing."
4: location → anchor: #location-prompt  bubble below status bar  "📍 Tell us where you're joining from — it's for the world map, totally optional."
5: key points → anchor: #summary-btn   bubble below status bar  "🧠 AI recaps what you missed. Tap any time — no FOMO."
6: name → anchor: #display-name         bubble below status bar  "✏️ That's your name. Tap it to change it. Be creative."
```

- [ ] **Step 1: Add first-visit flag detection**

In `participant.js`, find line 7:
```js
  const uuidStorage = document.cookie.includes('is_host=1') ? sessionStorage : localStorage;
```
Insert immediately after it (line 8), **before** `function getOrCreateUUID()` and before `let myUUID = getOrCreateUUID()`:
```js
  const _isFirstVisit = !uuidStorage.getItem(LS_UUID_KEY);
```
Critical: this line MUST appear before line 18 `let myUUID = getOrCreateUUID()`, otherwise `getOrCreateUUID()` will have already written the UUID and `_isFirstVisit` will always be `false`.

- [ ] **Step 2: Add `runOnboardingTourIfNeeded()` function**

Add this function after the `escHtml` function (around line 88):

```js
  const LS_TOUR_KEY = 'workshop_tour_shown';

  function runOnboardingTourIfNeeded() {
    if (!_isFirstVisit) return;
    if (localStorage.getItem(LS_TOUR_KEY)) return;
    localStorage.setItem(LS_TOUR_KEY, '1');

    const STEPS = [
      { selector: '#emoji-bar button[onclick*="☕"]', emoji: '☕', text: 'God, I need a coffee — tap this when you\'re running on fumes and need a break. No shame.' },
      { selector: '#emoji-bar button[onclick*="👍"]', emoji: '👍', text: 'Tap when the speaker says something brilliant. Their ego needs the fuel.' },
      { selector: '#emoji-bar button[onclick*="⚔️"]', emoji: '⚔️', text: 'Disagreement battle mode! Fight me on this — intellectually. Tap when you strongly disagree.' },
      { selector: '#emoji-bar button[onclick*="🔥"]', emoji: '🔥', text: 'This. Is. Fire. Tap when the content is genuinely mind-blowing.' },
      { selector: '#location-prompt',  emoji: '📍', text: 'Tell us where you\'re joining from — for the world map, totally optional.' },
      { selector: '#summary-btn',      emoji: '🧠', text: 'AI recaps what you missed. Tap any time. Zero FOMO.' },
      { selector: '#display-name',     emoji: '✏️', text: 'That\'s your name. Tap it to rename yourself. Be creative.' },
    ];

    const TOTAL = STEPS.length;
    let current = 0;
    let bubble = null;
    let glowEl = null;
    const STEP_DELAY_MS = 3000;
    let autoTimer = null;

    function clearGlow() {
      if (glowEl) { glowEl.classList.remove('tour-glow'); glowEl = null; }
    }

    function removeBubble() {
      if (bubble) { bubble.remove(); bubble = null; }
    }

    function finish() {
      clearAutoTimer();
      clearGlow();
      removeBubble();
    }

    function clearAutoTimer() {
      if (autoTimer) { clearTimeout(autoTimer); autoTimer = null; }
    }

    function showStep(index) {
      clearAutoTimer();
      clearGlow();
      removeBubble();

      if (index >= TOTAL) { finish(); return; }
      const step = STEPS[index];
      const anchor = document.querySelector(step.selector);
      if (!anchor) { showStep(index + 1); return; } // skip invisible step

      // Glow the anchor
      glowEl = anchor;
      glowEl.classList.add('tour-glow');

      // Build bubble
      bubble = document.createElement('div');
      bubble.className = 'tour-bubble';

      const emojiSpan = document.createElement('span');
      emojiSpan.className = 'tour-bubble-emoji';
      emojiSpan.textContent = step.emoji;

      const textSpan = document.createElement('span');
      textSpan.className = 'tour-bubble-text';
      textSpan.textContent = step.text;

      const footer = document.createElement('div');
      footer.className = 'tour-bubble-footer';

      const dots = document.createElement('div');
      dots.className = 'tour-dots';
      for (let i = 0; i < TOTAL; i++) {
        const dot = document.createElement('div');
        dot.className = 'tour-dot' + (i === index ? ' active' : '');
        dots.appendChild(dot);
      }

      const skipBtn = document.createElement('button');
      skipBtn.className = 'tour-skip';
      skipBtn.textContent = 'Skip';
      skipBtn.onclick = (e) => { e.stopPropagation(); finish(); };

      footer.appendChild(dots);
      footer.appendChild(skipBtn);

      bubble.appendChild(emojiSpan);
      bubble.appendChild(textSpan);
      bubble.appendChild(footer);
      document.body.appendChild(bubble);

      // Position bubble above or below anchor
      positionBubble(bubble, anchor);

      // Tap anywhere → advance
      function onTap(e) {
        if (e.target === skipBtn || skipBtn.contains(e.target)) return;
        document.removeEventListener('click', onTap, true);
        current++;
        showStep(current);
      }
      // Small delay so this click doesn't immediately fire
      setTimeout(() => document.addEventListener('click', onTap, true), 200);

      // Auto-advance after STEP_DELAY_MS
      autoTimer = setTimeout(() => {
        document.removeEventListener('click', onTap, true);
        current++;
        showStep(current);
      }, STEP_DELAY_MS);
    }

    function positionBubble(bub, anchor) {
      const rect = anchor.getBoundingClientRect();
      const bubW = 240;
      // Try to place bubble above anchor first, fallback below
      const spaceAbove = rect.top;
      const spaceBelow = window.innerHeight - rect.bottom;

      bub.style.width = bubW + 'px';

      if (spaceAbove > 140 || spaceAbove > spaceBelow) {
        // above anchor
        bub.classList.remove('arrow-top');
        const top = rect.top - 10; // will be adjusted after render
        bub.style.left = Math.max(8, Math.min(window.innerWidth - bubW - 8, rect.left + rect.width / 2 - bubW / 2)) + 'px';
        bub.style.top = '0px'; // temp
        requestAnimationFrame(() => {
          const bh = bub.getBoundingClientRect().height;
          bub.style.top = Math.max(8, rect.top - bh - 12) + 'px';
        });
      } else {
        // below anchor
        bub.classList.add('arrow-top');
        bub.style.top = (rect.bottom + 12) + 'px';
        bub.style.left = Math.max(8, Math.min(window.innerWidth - bubW - 8, rect.left + rect.width / 2 - bubW / 2)) + 'px';
      }
    }

    // Start after a short delay so page is settled
    setTimeout(() => showStep(0), 800);
  }
```

- [ ] **Step 3: Call `runOnboardingTourIfNeeded()` inside the WS `onopen` handler**

The WS connect function is named `connectWS` (not `connectWebSocket`). Find the line inside `connectWS` that makes the main screen visible:
```js
document.getElementById('main-screen').style.display = 'block';
```
Add the call right after it:
```js
    runOnboardingTourIfNeeded();
```
This is inside `ws.onopen`. The guard inside `runOnboardingTourIfNeeded()` (`_isFirstVisit` + localStorage flag) ensures it only runs once even if WS reconnects.

- [ ] **Step 4: Commit**
```bash
git add static/participant.js
git commit -m "feat(participant): add first-visit onboarding tour"
```

---

### Task 4: Add dev-reset gesture on version tag

**Files:**
- Modify: `static/participant.js` (append at end, after DOMContentLoaded or inline)

- [ ] **Step 1: Add version tag click handler**

At the bottom of `participant.js`, after all other code, append:

```js
  // Hidden dev-reset: click version tag to wipe all local state and reload
  (function setupDevReset() {
    const vt = document.getElementById('version-tag');
    if (!vt) return;
    vt.style.cursor = 'pointer';
    vt.addEventListener('click', () => {
      if (!confirm('Reset everything? This will log you out, clear all local state, and reload the page.')) return;
      // Clear all localStorage keys for this app
      ['workshop_participant_uuid', 'workshop_participant_name', 'workshop_custom_name',
       'workshop_vote', 'workshop_participant_location', 'workshop_tour_shown', 'workshop_wc_session']
        .forEach(k => localStorage.removeItem(k));
      sessionStorage.clear();
      // Clear cookies
      document.cookie.split(';').forEach(c => {
        document.cookie = c.replace(/^ +/, '').replace(/=.*/, '=;expires=' + new Date(0).toUTCString() + ';path=/');
      });
      location.reload();
    });
  })();
```

Note: The CSS already adds `cursor:pointer` on `#version-tag:hover` and brightens the text — added in Task 2.

- [ ] **Step 2: Verify manually**
  - Open participant page
  - Click the version tag text (bottom-right)
  - Confirm dialog appears
  - Say Yes → page reloads fresh, tour runs again

- [ ] **Step 3: Commit**
```bash
git add static/participant.js
git commit -m "feat(participant): hidden dev-reset on version tag click"
```

---

### Task 5: Push and verify on prod

- [ ] **Step 1: Fetch and rebase**
```bash
git fetch origin && git rebase origin/master
```

- [ ] **Step 2: Push to master**
```bash
git push origin HEAD:master
```

- [ ] **Step 3: Wait for Railway deploy (~45s)**

- [ ] **Step 4: Open a fresh incognito window** to `https://interact.victorrentea.ro/`

- [ ] **Step 5: Confirm tour plays** — 7 bubbles, auto-advance, skip works, no repeat on reload

- [ ] **Step 6: Confirm dev-reset** — click version tag → confirm → reload → tour plays again

- [ ] **Step 7: Screenshot** — capture at least one bubble visible on screen
