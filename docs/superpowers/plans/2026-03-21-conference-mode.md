# Conference Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a conference mode toggle that adapts the host and participant UIs for large audiences (100-350 people) — no names, no scores, big emoji reactions, compact host layout.

**Architecture:** Server-side `mode` field on `AppState` toggled via host badge. Mode propagates in every WebSocket broadcast. Participant JS conditionally renders onboarding/emoji based on mode. Host JS hides right column and shows QR in left panel when in conference mode.

**Tech Stack:** Python/FastAPI (backend), Vanilla JS/HTML/CSS (frontend), WebSocket broadcasts

**Spec:** `docs/superpowers/specs/2026-03-21-conference-mode-design.md`

---

### Task 1: Add `mode` field to AppState and broadcast it (with conditional field omission)

**Files:**
- Modify: `state.py` (AppState class — add `mode` field inside `reset()` so it resets properly)
- Modify: `messaging.py` (`build_participant_state`, `build_host_state`)

- [ ] **Step 1: Add `mode` field to AppState**

In `state.py`, add inside the `reset()` method alongside other fields:

```python
    self.mode: str = "workshop"  # "workshop" | "conference"
```

- [ ] **Step 2: Include `mode` in participant state broadcast with conditional omission**

In `messaging.py`, inside `build_participant_state()`, add `"mode"` to the returned dict. Also conditionally omit score and avatar in conference mode:

```python
    "mode": state.mode,
    "my_score": 0 if state.mode == "conference" else state.scores.get(pid, 0),
    "my_avatar": "" if state.mode == "conference" else state.participant_avatars.get(pid, ""),
```

Replace the existing `my_score` and `my_avatar` lines with these conditional versions.

- [ ] **Step 3: Include `mode` in host state broadcast**

In `messaging.py`, inside `build_host_state()`, add `"mode"` to the returned dict:

```python
    "mode": state.mode,
```

- [ ] **Step 4: Verify server starts**

Run: `cd /Users/victorrentea/conductor/workspaces/training-assistant/charlotte && python3 -c "from state import state; print(state.mode)"`
Expected: `workshop`

- [ ] **Step 5: Commit**

```bash
git add state.py messaging.py
git commit -m "feat: add mode field to AppState and broadcasts"
```

---

### Task 2: Add POST /api/mode endpoint

**Files:**
- Modify: `main.py` (add imports at top level, add route)

- [ ] **Step 1: Add the mode toggle endpoint in main.py**

Add top-level imports (alongside existing imports):

```python
from pydantic import BaseModel
from fastapi import FastAPI, Depends, HTTPException
```

(Update the existing `from fastapi import FastAPI, Depends` line to include `HTTPException`.)

Add the model and endpoint after the existing router includes, before static files mount:

```python
class ModeRequest(BaseModel):
    mode: str

@app.post("/api/mode", dependencies=[Depends(require_host_auth)])
async def set_mode(req: ModeRequest):
    if req.mode not in ("workshop", "conference"):
        raise HTTPException(400, "mode must be 'workshop' or 'conference'")
    state.mode = req.mode
    await broadcast_state()
    return {"mode": state.mode}
```

Note: `broadcast_state` is already imported at the top level in `main.py` (from `messaging`). If not, add it.

- [ ] **Step 2: Test endpoint manually**

Run server, then:
```bash
source secrets.env && curl -s -u "$HOST_USERNAME:$HOST_PASSWORD" -X POST http://localhost:8000/api/mode -H 'Content-Type: application/json' -d '{"mode":"conference"}' | python3 -m json.tool
```
Expected: `{"mode": "conference"}`

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: add POST /api/mode endpoint for conference toggle"
```

---

### Task 3: Skip set_name requirement in conference mode

**Files:**
- Modify: `routers/ws.py` (between `named = is_host or is_overlay` and the `try: while True:` message loop)

- [ ] **Step 1: Allow unnamed participants in conference mode**

In `routers/ws.py`, find the line `named = is_host or is_overlay` (around line 71). Right after it, before the `try: while True:` message loop (around line 73), add:

```python
    # In conference mode, auto-name and mark as named immediately
    if state.mode == "conference" and not named:
        state.participant_names[participant_id] = ""
        named = True
        from messaging import build_participant_state
        await websocket.send_text(json.dumps(build_participant_state(participant_id)))
```

Check that `build_participant_state` is available — if it's not already imported in ws.py, add the import at the top of the file (preferred) or keep the local import above.

- [ ] **Step 2: Test by connecting a participant WebSocket in conference mode**

1. Set mode to conference via API
2. Open participant page — should connect without name prompt
3. Verify WS doesn't wait for `set_name`

- [ ] **Step 3: Commit**

```bash
git add routers/ws.py
git commit -m "feat: skip set_name requirement in conference mode"
```

---

### Task 4: Host UI — mode toggle badge and conference layout

This task combines the toggle badge AND the layout function so they can be tested together (renderMode calls applyConferenceLayout).

**Files:**
- Modify: `static/host.html` (badge bar + QR container in left column + conference pax count badge)
- Modify: `static/host.js` (toggle handler, renderMode, applyConferenceLayout, state handler)
- Modify: `static/host.css` (no changes needed — layout is set via JS inline styles)

- [ ] **Step 1: Add conference QR container in left column HTML**

In `static/host.html`, inside the left column, after the tab content area and before `.left-status-bar`, add:

```html
<div id="conference-qr" class="conference-qr-container">
  <div id="conference-qr-code" style="background:#fff; padding:12px; border-radius:12px; display:inline-block;"></div>
  <div style="margin-top:.5rem; font-size:.75rem; color:var(--text-muted);">Scan to join</div>
</div>
```

- [ ] **Step 2: Add conference badges to status bar**

In `static/host.html`, inside `.left-status-bar`, add before the closing `</div>`:

```html
<span id="conference-pax-count" class="badge connected" style="display:none" title="Connected participants">👥 0</span>
<span id="mode-badge" class="badge connected" title="Workshop mode — click to switch to Conference" onclick="toggleMode()" style="cursor:pointer">🎓</span>
```

- [ ] **Step 3: Add CSS for conference QR container**

In `static/host.css`, add:

```css
.conference-qr-container {
  display: none;
  text-align: center;
  padding: 1rem 0;
  flex: 1;
  flex-direction: column;
  justify-content: center;
  align-items: center;
}
```

- [ ] **Step 4: Add all conference mode JS functions in host.js**

Add a global variable at the top:
```javascript
let currentMode = 'workshop';
```

Add the functions:
```javascript
async function toggleMode() {
  const newMode = (currentMode === 'workshop') ? 'conference' : 'workshop';
  await fetch('/api/mode', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: newMode }),
  });
}

function renderMode(mode) {
  const badge = document.getElementById('mode-badge');
  if (!badge) return;
  badge.textContent = mode === 'conference' ? '🎤' : '🎓';
  badge.title = mode === 'conference' ? 'Conference mode — click to switch to Workshop' : 'Workshop mode — click to switch to Conference';
  badge.className = 'badge ' + (mode === 'conference' ? 'error' : 'connected');
  applyConferenceLayout(mode === 'conference');
}

function applyConferenceLayout(isConference) {
  const rightCol = document.querySelector('.host-col-right');
  const grid = document.querySelector('.host-columns');
  const confQR = document.getElementById('conference-qr');
  const confPax = document.getElementById('conference-pax-count');
  const debateTab = document.getElementById('tab-debate');

  if (isConference) {
    rightCol.style.display = 'none';
    grid.style.gridTemplateColumns = '25% 1fr';
    confQR.style.display = 'flex';
    confPax.style.display = '';
    if (debateTab) debateTab.style.display = 'none';
    // Generate QR in left panel
    const qrContainer = document.getElementById('conference-qr-code');
    qrContainer.innerHTML = '';
    const link = document.getElementById('participant-link');
    if (link && link.href && typeof QRCode !== 'undefined') {
      new QRCode(qrContainer, { text: link.href, width: 160, height: 160, colorDark: '#000', colorLight: '#fff' });
    }
  } else {
    rightCol.style.display = '';
    grid.style.gridTemplateColumns = '25% 1fr 25%';
    confQR.style.display = 'none';
    confPax.style.display = 'none';
    if (debateTab) debateTab.style.display = '';
  }
}
```

- [ ] **Step 5: Hook into state message handler**

In the `state` message handler (around line 142), add:
```javascript
if (msg.mode) {
  currentMode = msg.mode;
  renderMode(msg.mode);
}
```

Also update the participant count badge:
```javascript
const confPax = document.getElementById('conference-pax-count');
if (confPax && currentMode === 'conference') {
  confPax.textContent = '👥 ' + (names ? names.length : 0);
}
```

- [ ] **Step 6: Test mode toggle and conference layout**

1. Open host panel
2. Click mode badge → should toggle between 🎓 and 🎤
3. In conference mode: right column hidden, QR in left panel, participant count badge visible, Debate tab hidden
4. Toggle back to workshop: everything restored

- [ ] **Step 7: Commit**

```bash
git add static/host.html static/host.js static/host.css
git commit -m "feat: host conference mode layout with toggle badge"
```

---

### Task 5: Host UI — badge compaction and tab reorder

**Files:**
- Modify: `static/host.html` (tab order)
- Modify: `static/host.js` (badge rendering functions, switchTab tab list)

- [ ] **Step 1: Reorder tabs — move Debate to last position**

In `static/host.html`, change the tab-bar button order from:
```
Poll, Words, Q&A, Debate, Code
```
to:
```
Poll, Words, Q&A, Code, Debate
```

Move the `#tab-debate` button HTML after `#tab-codereview`. Also reorder the corresponding `#tab-content-debate` div after `#tab-content-codereview`.

- [ ] **Step 2: Update switchTab tab list in host.js**

In `static/host.js`, find `switchTab` function — update the array from `['poll', 'wordcloud', 'qa', 'debate', 'codereview']` to `['poll', 'wordcloud', 'qa', 'codereview', 'debate']`.

- [ ] **Step 3: Compact badge text in JS rendering functions**

In `static/host.js`, update badge rendering functions to use icon-only text:
- `setBadge()`: change both `'Server'` occurrences to `'🟢'` (the `.connected`/`.disconnected` class already handles the color)
- `renderDaemonStatus()`: change all `'Agent'` textContent to `'🤖'`
- `renderNotesStatus()` (find where `.txt` or notes badge text is set): change to `'📝'`
- `renderSummaryBadge()` (find where `Lessons` text is set): change `'Lessons'` prefix to `'🧠'`. If it shows a count like `Lessons (3)`, change to `'🧠 3'` (or just `'🧠'` when count is 0)

Keep all tooltip (`title`) text unchanged for discoverability.

- [ ] **Step 4: Update host.html badge initial text to match**

Change the initial badge innerHTML in `.left-status-bar`:
- `Server` → `🟢`
- `Agent` → `🤖`
- `.txt` → `📝`
- `Lessons` → `🧠`

- [ ] **Step 5: Test badge compaction and tab order**

Open host panel, verify:
- Badges show icons only (🟢, 🤖, 📝, 🧠, 💬, ❤️, $0.00, 👥, 🎓)
- Tab order: Poll, Words, Q&A, Code, Debate

- [ ] **Step 6: Commit**

```bash
git add static/host.html static/host.js
git commit -m "feat: compact badges to icons, reorder tabs (debate last)"
```

---

### Task 6: Participant UI — conference mode emoji grid and conditional rendering

**Files:**
- Modify: `static/participant.html` (add conference emoji grid)
- Modify: `static/participant.js` (mode-conditional rendering, skip onboarding)
- Modify: `static/participant.css` (emoji grid styles)

- [ ] **Step 1: Add conference emoji grid HTML**

In `static/participant.html`, add a new div after `#emoji-bar`:

```html
<div id="conference-emoji-grid" style="display:none;">
  <div class="emoji-grid">
    <button class="emoji-grid-btn" onclick="sendEmoji('❤️')">❤️</button>
    <button class="emoji-grid-btn" onclick="sendEmoji('🔥')">🔥</button>
    <button class="emoji-grid-btn" onclick="sendEmoji('👏')">👏</button>
    <button class="emoji-grid-btn" onclick="sendEmoji('😂')">😂</button>
    <button class="emoji-grid-btn" onclick="sendEmoji('🤯')">🤯</button>
    <button class="emoji-grid-btn" onclick="sendEmoji('💡')">💡</button>
    <button class="emoji-grid-btn" onclick="sendEmoji('👍')">👍</button>
    <button class="emoji-grid-btn" onclick="sendEmoji('🤔')">🤔</button>
    <button class="emoji-grid-btn" onclick="sendEmoji('💪')">💪</button>
  </div>
</div>
```

- [ ] **Step 2: Add conference emoji grid CSS**

In `static/participant.css`, add at the end:

```css
/* Conference mode emoji grid */
#conference-emoji-grid {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
  padding: 1rem;
}
.emoji-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
  max-width: 320px;
  width: 100%;
}
.emoji-grid-btn {
  font-size: 3rem;
  padding: 1.2rem;
  border: 2px solid var(--border);
  border-radius: 16px;
  background: var(--surface);
  cursor: pointer;
  transition: transform 0.1s, background 0.15s;
  user-select: none;
  -webkit-user-select: none;
  aspect-ratio: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
.emoji-grid-btn:active {
  transform: scale(0.9);
  background: var(--border);
}
```

- [ ] **Step 3: Add mode-conditional rendering in participant.js**

Add a global variable near the top (with other globals):
```javascript
let currentMode = 'workshop';
```

In the `state` message handler (inside `handleMessage` or `ws.onmessage`), add early:
```javascript
if (msg.mode && msg.mode !== currentMode) {
  currentMode = msg.mode;
  applyParticipantMode(msg.mode);
}
// Always track mode even if same (for initial page load)
if (msg.mode) currentMode = msg.mode;
```

Implement the mode switcher:
```javascript
function applyParticipantMode(mode) {
  const isConference = mode === 'conference';
  // Hide/show status bar elements
  const statusLeft = document.querySelector('.status-left');
  if (statusLeft) statusLeft.style.display = isConference ? 'none' : '';
  const myScore = document.getElementById('my-score');
  if (myScore) myScore.style.display = isConference ? 'none' : '';
  const locPrompt = document.getElementById('location-prompt');
  if (locPrompt) locPrompt.style.display = isConference ? 'none' : '';
  const notifBtn = document.getElementById('notif-btn');
  if (notifBtn) notifBtn.style.display = isConference ? 'none' : '';

  // Toggle emoji displays
  const emojiBar = document.getElementById('emoji-bar');
  if (emojiBar) emojiBar.style.display = isConference ? 'none' : '';
  const confGrid = document.getElementById('conference-emoji-grid');
  if (confGrid) confGrid.style.display = isConference ? '' : 'none';
}
```

- [ ] **Step 4: Modify renderContent for conference mode**

In `renderContent()`, add at the very top of the function:

```javascript
  // Conference mode: show emoji grid when idle, hide when activity active
  const confGrid = document.getElementById('conference-emoji-grid');
  if (currentMode === 'conference') {
    if (!currentActivity || currentActivity === 'none') {
      document.getElementById('content').innerHTML = '';
      if (confGrid) confGrid.style.display = '';
      return;
    } else {
      if (confGrid) confGrid.style.display = 'none';
    }
  }
```

Where `currentActivity` is however the current activity is tracked in participant.js (likely from `msg.current_activity` in the state). Check the actual variable name used.

- [ ] **Step 5: Skip onboarding in conference mode**

Find the onboarding checklist rendering code in `renderContent()`. At the top of the onboarding section (where it checks if name/location/notifications are complete), add:

```javascript
if (currentMode === 'conference') {
  // No onboarding in conference mode
} else {
  // existing onboarding code
}
```

Wrap the existing onboarding block in the `else`.

- [ ] **Step 6: Test participant conference mode**

1. Set mode to conference via host toggle
2. Open participant page
3. Verify: no name bar, no score, no location prompt, no notification prompt
4. Verify: 3x3 emoji grid shown as main content
5. Tap emojis — verify they send to overlay
6. Start a poll from host → emoji grid hides, poll shows
7. Close poll → emoji grid returns

- [ ] **Step 7: Commit**

```bash
git add static/participant.html static/participant.js static/participant.css
git commit -m "feat: participant conference mode with 3x3 emoji grid"
```

---

### Task 7: Update CLAUDE.md auth scope

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add `/api/mode` to the host auth scope list**

In `CLAUDE.md`, find the list of host-auth-protected endpoints and add `/api/mode`.

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add /api/mode to host auth scope"
```

---

### Task 8: Integration testing and polish

**Files:**
- All modified files

- [ ] **Step 1: Full flow test**

1. Start server: `python3 -m uvicorn main:app --reload --port 8000`
2. Open host panel at http://localhost:8000/host
3. Toggle to conference mode (🎓 → 🎤)
4. Verify host: right column hidden, QR in left panel, participant count badge visible, Debate tab hidden
5. Open participant in new tab at http://localhost:8000/
6. Verify participant: no name prompt, emoji grid shown, no onboarding
7. Send emoji reactions — verify they arrive at overlay
8. Start poll from host → participant sees poll, emoji grid hides
9. Vote → poll works normally
10. Close poll → emoji grid returns
11. Test word cloud similarly
12. Test Q&A — verify questions appear without author name
13. Test code review — verify line selections work
14. Toggle back to workshop mode → verify everything restores (name bar returns, normal emoji bar, right column visible, Debate tab visible)

- [ ] **Step 2: Fix any issues found**

Address visual glitches, missing state, or broken flows.

- [ ] **Step 3: Take screenshots for proof**

Capture: host in conference mode, participant emoji grid, participant during poll.

- [ ] **Step 4: Final commit if needed**

```bash
git add -A
git commit -m "fix: conference mode polish and integration fixes"
```
