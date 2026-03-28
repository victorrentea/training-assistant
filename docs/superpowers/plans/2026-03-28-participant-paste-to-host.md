# Participant Paste-to-Host Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let participants send text snippets to the host via a floating 📋 button; host sees inline clipboard icons per participant, clicks to copy and dismiss.

**Architecture:** New `paste_texts` dict on AppState stores `{id, text}` entries per participant UUID. Participant sends text via WebSocket `paste_text` message; host dismisses via `paste_dismiss` message with paste ID. Both trigger `broadcast_participant_update()` which includes paste_texts in the host participant list.

**Tech Stack:** Python/FastAPI (WebSocket handler), vanilla JS, CSS

**Spec:** `docs/superpowers/specs/2026-03-28-participant-paste-to-host-design.md`

---

### Task 1: Backend State — Add paste_texts to AppState

**Files:**
- Modify: `core/state.py:31-109` (reset method)

- [ ] **Step 1: Add paste_texts and paste_next_id to AppState.reset()**

Add after the existing participant dict fields (around line 42):

```python
self.paste_texts: dict[str, list[dict]] = {}  # uuid → [{id: int, text: str}, ...]
self.paste_next_id: int = 0
```

- [ ] **Step 2: Commit**

```bash
git add core/state.py
git commit -m "feat(paste): add paste_texts state to AppState"
```

---

### Task 2: Backend State Builder — Include paste_texts in host participant list

**Files:**
- Modify: `core/state_builder.py:17-36` (_build_host_participants_list)

- [ ] **Step 1: Add paste_texts to participant dict in _build_host_participants_list()**

After the existing fields (around line 31, after the `online` field), add conditionally:

```python
paste_entries = state.paste_texts.get(pid, [])
if paste_entries:
    participant["paste_texts"] = paste_entries
```

- [ ] **Step 2: Commit**

```bash
git add core/state_builder.py
git commit -m "feat(paste): include paste_texts in host participant list"
```

---

### Task 3: WebSocket Handler — paste_text and paste_dismiss messages

**Files:**
- Modify: `features/ws/router.py` (add two new elif branches in the message handler)

- [ ] **Step 1: Add paste_text handler**

Add a new `elif` branch after the last existing handler (after `codereview_deselect`, around line 432). Follow the wordcloud_word pattern:

```python
elif msg_type == "paste_text":
    text = str(data.get("text", ""))
    if text and len(text) <= 102400 and not is_host:  # 100KB limit
        entries = state.paste_texts.setdefault(pid, [])
        if len(entries) < 10:  # max 10 pending per participant
            state.paste_next_id += 1
            entries.append({"id": state.paste_next_id, "text": text})
            await broadcast_participant_update()
```

- [ ] **Step 2: Add paste_dismiss handler for host**

Add another `elif` branch, gated to host only:

```python
elif msg_type == "paste_dismiss":
    if is_host:
        target_uuid = str(data.get("uuid", ""))
        paste_id = data.get("paste_id")
        if target_uuid in state.paste_texts and paste_id is not None:
            state.paste_texts[target_uuid] = [
                e for e in state.paste_texts[target_uuid] if e["id"] != paste_id
            ]
            if not state.paste_texts[target_uuid]:
                del state.paste_texts[target_uuid]
            await broadcast_participant_update()
```

- [ ] **Step 3: Commit**

```bash
git add features/ws/router.py
git commit -m "feat(paste): handle paste_text and paste_dismiss WebSocket messages"
```

---

### Task 4: Participant UI — Floating 📋 button

**Files:**
- Modify: `static/participant.html` (add button + modal HTML)
- Modify: `static/participant.css` (add styles)

- [ ] **Step 1: Add the floating paste button to participant.html**

Add right before the `<div id="emoji-bar">` (line 132):

```html
<button id="paste-btn" class="paste-floating-btn" onclick="openPasteModal()" title="Send text to host">📋</button>
```

- [ ] **Step 2: Add the paste modal to participant.html**

Add after the emoji bar section (after line 163, after the conference-emoji-grid div):

```html
<div id="paste-overlay" class="summary-overlay" onclick="closePasteModal()">
  <div class="summary-dialog paste-dialog" onclick="event.stopPropagation()">
    <div class="summary-header">
      <span>📋 Send Text to Host</span>
      <button class="summary-close" onclick="closePasteModal()">✕</button>
    </div>
    <textarea id="paste-textarea" class="paste-textarea" placeholder="Paste your text here..." oninput="document.getElementById('paste-send-btn').disabled = !this.value.trim()"></textarea>
    <button id="paste-send-btn" class="paste-send-btn" disabled onclick="sendPasteText()">Send</button>
  </div>
</div>
```

- [ ] **Step 3: Add styles to participant.css**

Add at the end of the file, before any media queries:

```css
/* Paste-to-host floating button */
.paste-floating-btn {
  position: fixed;
  bottom: 60px;
  right: 12px;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text);
  font-size: 1.3rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 3002;
  transition: transform .1s, background .15s, border-color .15s;
  padding: 0;
  line-height: 1;
}
.paste-floating-btn:hover {
  background: rgba(20, 20, 35, 0.97);
  border-color: var(--accent);
}
.paste-floating-btn:active { transform: scale(0.85); }

/* Paste modal */
.paste-dialog {
  max-width: 500px;
  width: 90vw;
}
.paste-textarea {
  width: 100%;
  min-height: 150px;
  max-height: 50vh;
  background: var(--bg);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: .75rem;
  font-family: monospace;
  font-size: .85rem;
  resize: vertical;
  margin-bottom: .75rem;
}
.paste-textarea:focus {
  outline: none;
  border-color: var(--accent);
}
.paste-send-btn {
  width: 100%;
  padding: .6rem;
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: .95rem;
  font-weight: 600;
  cursor: pointer;
}
.paste-send-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.paste-send-btn:not(:disabled):hover {
  filter: brightness(1.15);
}
```

- [ ] **Step 4: Commit**

```bash
git add static/participant.html static/participant.css
git commit -m "feat(paste): add floating paste button and modal to participant UI"
```

---

### Task 5: Participant JS — Modal logic and WebSocket send

**Files:**
- Modify: `static/participant.js` (add modal functions and mode-aware visibility)

- [ ] **Step 1: Add paste modal functions**

Add near the existing modal functions (around line 518, after closeSummaryModal):

```javascript
function openPasteModal() {
  const overlay = document.getElementById('paste-overlay');
  if (overlay) {
    overlay.classList.add('open');
    const ta = document.getElementById('paste-textarea');
    if (ta) { ta.value = ''; ta.focus(); }
    document.getElementById('paste-send-btn').disabled = true;
  }
}

function closePasteModal() {
  const overlay = document.getElementById('paste-overlay');
  if (overlay) overlay.classList.remove('open');
}

function sendPasteText() {
  const ta = document.getElementById('paste-textarea');
  const text = ta ? ta.value : '';
  if (!text.trim() || !ws) return;
  if (text.length > 102400) {
    alert('Text too large (max 100KB)');
    return;
  }
  ws.send(JSON.stringify({ type: 'paste_text', text: text }));
  closePasteModal();
  showPasteToast();
}

function showPasteToast() {
  const toast = document.createElement('div');
  toast.textContent = 'Sent!';
  toast.style.cssText = 'position:fixed;bottom:110px;right:12px;background:var(--accent);color:#fff;padding:.4rem .9rem;border-radius:8px;font-weight:600;font-size:.85rem;z-index:9999;opacity:1;transition:opacity .5s;';
  document.body.appendChild(toast);
  setTimeout(() => { toast.style.opacity = '0'; }, 1000);
  setTimeout(() => toast.remove(), 1500);
}
```

- [ ] **Step 2: Add closePasteModal to closeParticipantModals()**

In the existing `closeParticipantModals()` function (around line 520), add `closePasteModal();` alongside the other modal close calls.

- [ ] **Step 3: Add mode-aware visibility for the paste button**

In the existing `applyParticipantMode(mode)` function (around line 3172), add logic to hide/show the paste button:

```javascript
// Inside applyParticipantMode, add:
const pasteBtn = document.getElementById('paste-btn');
if (pasteBtn) pasteBtn.style.display = mode === 'conference' ? 'none' : 'flex';
```

- [ ] **Step 4: Commit**

```bash
git add static/participant.js
git commit -m "feat(paste): add paste modal logic and mode-aware visibility"
```

---

### Task 6: Host UI — Clipboard icons in participant list

**Files:**
- Modify: `static/host.js` (renderParticipantList function, around lines 1206-1262)
- Modify: `static/host.css` (add paste icon styles)

- [ ] **Step 1: Add paste icons to renderParticipantList in host.js**

Inside the `renderParticipantList` function, in the `.map()` callback (around line 1218), after extracting participant data and before the return statement:

```javascript
// After: const online = participant.online !== false;
const pasteTexts = participant.paste_texts || [];
const pasteIcons = pasteTexts.map((entry, i) => {
  const preview = (entry.text.length > 100 ? entry.text.substring(0, 100) + '…' : entry.text).replace(/\n/g, ' ');
  return `<span class="paste-icon" title="${escHtml(preview)}" data-uuid="${escHtml(pid)}" data-paste-id="${entry.id}" onclick="copyAndDismissPaste(this)">📋</span>`;
}).join('');
```

Then insert `${pasteIcons}` in the returned `<li>` HTML, after the name span and before `${scoreTag}`:

```javascript
return `<li class="${online ? 'online' : 'offline'}"><span class="pax-name" title="IP: ${escHtml(ip)}">${debateIcon}${avatarHtml}<span class="pax-name-text">${escHtml(name)}</span></span>${pasteIcons}${scoreTag}${locLabel ? `<span class="pax-location"...>...</span>` : ''}</li>`;
```

(Integrate into the existing return template — do not duplicate the full line, just add `${pasteIcons}` in the right position.)

- [ ] **Step 2: Add copyAndDismissPaste function to host.js**

Add near the bottom of host.js, alongside other utility functions:

```javascript
function copyAndDismissPaste(el) {
  const uuid = el.dataset.uuid;
  const pasteId = parseInt(el.dataset.pasteId, 10);
  // Find the full text from cached participant data
  const participant = participantDataById[uuid];
  const entry = (participant?.paste_texts || []).find(e => e.id === pasteId);
  if (entry) {
    navigator.clipboard.writeText(entry.text).then(() => {
      el.style.transition = 'opacity .3s';
      el.style.opacity = '0';
      setTimeout(() => el.remove(), 300);
    });
  }
  // Dismiss from server
  if (ws) {
    ws.send(JSON.stringify({ type: 'paste_dismiss', uuid: uuid, paste_id: pasteId }));
  }
}
```

- [ ] **Step 3: Add paste icon styles to host.css**

```css
.paste-icon {
  cursor: pointer;
  font-size: .85rem;
  margin-left: .2rem;
  opacity: 0.8;
  transition: opacity .15s, transform .15s;
}
.paste-icon:hover {
  opacity: 1;
  transform: scale(1.15);
}
```

- [ ] **Step 4: Commit**

```bash
git add static/host.js static/host.css
git commit -m "feat(paste): show clipboard icons in host participant list with copy+dismiss"
```

---

### Task 7: Manual End-to-End Test

- [ ] **Step 1: Start the server**

```bash
python3 -m uvicorn main:app --reload --port 8000
```

- [ ] **Step 2: Open host and participant pages**

- Host: http://localhost:8000/host (enter credentials)
- Participant: http://localhost:8000/ (set a name)

- [ ] **Step 3: Verify paste button visible in workshop mode**

Confirm the 📋 button appears in bottom-right of participant page.

- [ ] **Step 4: Test the paste flow**

1. Click 📋 on participant page → modal opens
2. Paste some text → Send button enables → click Send
3. Modal closes, "Sent!" toast appears briefly
4. On host page, participant row shows a 📋 icon
5. Hover the icon → tooltip shows first ~100 chars
6. Click the icon → text copied to host clipboard, icon fades and disappears

- [ ] **Step 5: Test multiple texts**

Send 2-3 texts from same participant → host sees multiple 📋 icons → dismiss each one by clicking.

- [ ] **Step 6: Verify conference mode hides button**

Switch to conference mode on host → paste button disappears on participant page.

- [ ] **Step 7: Final commit**

```bash
git add -A
git commit -m "feat: participant paste-to-host — complete feature"
git push origin master
```
