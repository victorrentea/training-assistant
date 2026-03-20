# Code Review Activity — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Code Review activity where the host pushes a code snippet, participants flag problematic lines, and the host reveals correct lines one by one — awarding points and sparking discussion.

**Architecture:** New `CODEREVIEW` activity type following the existing pattern: state fields in `AppState`, a new REST router, WebSocket message handlers, and UI rendering in both host and participant pages. Two-phase flow: blind selection → host-driven review.

**Tech Stack:** Python/FastAPI backend, vanilla JS frontend, highlight.js (CDN) for syntax highlighting.

**Spec:** `docs/superpowers/specs/2026-03-20-code-review-activity-design.md`

---

## File Structure

| File | Role |
|------|------|
| `state.py` | Add `CODEREVIEW` enum value + code review state fields |
| `routers/codereview.py` | New — REST endpoints (create, status, confirm-line, clear) |
| `routers/ws.py` | Add `codereview_select` / `codereview_deselect` handlers |
| `messaging.py` | Add code review data to participant + host state builders |
| `main.py` | Register codereview router |
| `static/host.html` | Add Code Review tab + content div + center panel |
| `static/host.js` | Code review rendering: create form, heatmap, side panel, confirm flow |
| `static/host.css` | Heatmap, side panel, confirm button styles |
| `static/participant.html` | Add highlight.js CDN links |
| `static/participant.js` | Code review screen: line selection, review phase, percentages |
| `static/participant.css` | Line selection, review phase styles |

---

### Task 1: State Model

**Files:**
- Modify: `state.py:8-12` (ActivityType enum)
- Modify: `state.py:24-49` (AppState fields)

- [ ] **Step 1: Add CODEREVIEW to ActivityType enum**

In `state.py`, add `CODEREVIEW = "codereview"` after the `QA = "qa"` line:

```python
class ActivityType(str, Enum):
    NONE = "none"
    POLL = "poll"
    WORDCLOUD = "wordcloud"
    QA = "qa"
    CODEREVIEW = "codereview"
```

- [ ] **Step 2: Add code review state fields to AppState**

In the `reset()` method of `AppState` (around line 45, after the Q&A fields), add:

```python
# Code Review state
self.codereview_snippet: str | None = None
self.codereview_language: str | None = None
self.codereview_phase: str = "idle"  # "idle" | "selecting" | "reviewing"
self.codereview_selections: dict[str, set[int]] = {}  # uuid → set of line numbers
self.codereview_confirmed: set[int] = set()  # lines host confirmed
```

- [ ] **Step 3: Verify server starts**

Run: `python3 -m uvicorn main:app --port 8000 &` then `curl -s http://localhost:8000/api/status | python3 -m json.tool`

Expected: Server starts successfully, status endpoint responds.

- [ ] **Step 4: Commit**

```bash
git add state.py
git commit -m "feat(codereview): add CODEREVIEW activity type and state fields"
```

---

### Task 2: REST Router

**Files:**
- Create: `routers/codereview.py`
- Modify: `main.py:6-26` (register router)

- [ ] **Step 1: Create `routers/codereview.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_host_auth
from messaging import broadcast_state
from state import state, ActivityType

router = APIRouter()


class CodeReviewCreate(BaseModel):
    snippet: str
    language: str | None = None


class CodeReviewStatus(BaseModel):
    open: bool


class CodeReviewConfirmLine(BaseModel):
    line: int


@router.post("/api/codereview", dependencies=[Depends(require_host_auth)])
async def create_codereview(body: CodeReviewCreate):
    snippet = body.snippet.strip()
    if not snippet:
        raise HTTPException(400, "Snippet cannot be empty")
    lines = snippet.split("\n")
    if len(lines) > 50:
        raise HTTPException(400, "Snippet too long (max 50 lines)")

    state.codereview_snippet = snippet
    state.codereview_language = body.language
    state.codereview_phase = "selecting"
    state.codereview_selections = {}
    state.codereview_confirmed = set()
    state.current_activity = ActivityType.CODEREVIEW
    await broadcast_state()
    return {"ok": True}


@router.put("/api/codereview/status", dependencies=[Depends(require_host_auth)])
async def set_codereview_status(body: CodeReviewStatus):
    if state.current_activity != ActivityType.CODEREVIEW:
        raise HTTPException(400, "No code review active")
    if not body.open:
        state.codereview_phase = "reviewing"
    # open=true is a no-op (re-opening not supported)
    await broadcast_state()
    return {"ok": True, "phase": state.codereview_phase}


@router.put("/api/codereview/confirm-line", dependencies=[Depends(require_host_auth)])
async def confirm_codereview_line(body: CodeReviewConfirmLine):
    if state.current_activity != ActivityType.CODEREVIEW:
        raise HTTPException(400, "No code review active")
    if state.codereview_phase != "reviewing":
        raise HTTPException(400, "Not in reviewing phase")
    if state.codereview_snippet is None:
        raise HTTPException(400, "No snippet loaded")

    total_lines = len(state.codereview_snippet.split("\n"))
    if body.line < 1 or body.line > total_lines:
        raise HTTPException(400, f"Invalid line number: {body.line}")
    if body.line in state.codereview_confirmed:
        raise HTTPException(400, f"Line {body.line} already confirmed")

    state.codereview_confirmed.add(body.line)

    # Award 200 points to every participant who selected this line
    for pid, selections in state.codereview_selections.items():
        if body.line in selections:
            state.scores[pid] = state.scores.get(pid, 0) + 200

    await broadcast_state()
    return {"ok": True, "confirmed": list(state.codereview_confirmed)}


@router.delete("/api/codereview", dependencies=[Depends(require_host_auth)])
async def clear_codereview():
    state.codereview_snippet = None
    state.codereview_language = None
    state.codereview_phase = "idle"
    state.codereview_selections = {}
    state.codereview_confirmed = set()
    state.current_activity = ActivityType.NONE
    await broadcast_state()
    return {"ok": True}
```

- [ ] **Step 2: Register the router in `main.py`**

Add to imports (line 6):
```python
from routers import ws, poll, scores, quiz, pages, wordcloud, activity, qa, codereview
```

Add after the last `include_router` call (line 26):
```python
app.include_router(codereview.router)
```

- [ ] **Step 3: Verify endpoints load**

Run: `curl -s http://localhost:8000/openapi.json | python3 -c "import sys,json; paths=json.load(sys.stdin)['paths']; [print(p) for p in paths if 'codereview' in p]"`

Expected: Shows `/api/codereview`, `/api/codereview/status`, `/api/codereview/confirm-line`.

- [ ] **Step 4: Commit**

```bash
git add routers/codereview.py main.py
git commit -m "feat(codereview): add REST endpoints for create, status, confirm-line, clear"
```

---

### Task 3: WebSocket Message Handlers

**Files:**
- Modify: `routers/ws.py:88-160` (message dispatch chain)

- [ ] **Step 1: Add codereview_select and codereview_deselect handlers**

In `routers/ws.py`, add the following before the `except WebSocketDisconnect` block (after the `qa_upvote` handler, around line 160):

```python
elif msg_type == "codereview_select":
    line = data.get("line")
    if (state.current_activity == ActivityType.CODEREVIEW
            and state.codereview_phase == "selecting"
            and state.codereview_snippet is not None
            and isinstance(line, int)
            and 1 <= line <= len(state.codereview_snippet.split("\n"))):
        if participant_id not in state.codereview_selections:
            state.codereview_selections[participant_id] = set()
        state.codereview_selections[participant_id].add(line)
        await broadcast_state()

elif msg_type == "codereview_deselect":
    line = data.get("line")
    if (state.current_activity == ActivityType.CODEREVIEW
            and state.codereview_phase == "selecting"
            and isinstance(line, int)
            and participant_id in state.codereview_selections):
        state.codereview_selections[participant_id].discard(line)
        await broadcast_state()
```

Also ensure `ActivityType` is imported in `ws.py`. Check the existing imports — it may already be imported via `from state import state, ActivityType`. If not, add it.

- [ ] **Step 2: Verify by starting the server**

Run: `python3 -m uvicorn main:app --port 8000`

Expected: Server starts with no import errors.

- [ ] **Step 3: Commit**

```bash
git add routers/ws.py
git commit -m "feat(codereview): add WebSocket handlers for line select/deselect"
```

---

### Task 4: Broadcast State (messaging.py)

**Files:**
- Modify: `messaging.py:57-72` (build_participant_state)
- Modify: `messaging.py:75-111` (build_host_state)

- [ ] **Step 1: Add code review data to `build_participant_state()`**

In `messaging.py`, inside `build_participant_state()`, add the following key to the return dict (after the `qa_questions` line, around line 71):

```python
"codereview": _build_codereview_for_participant(pid),
```

Then add the helper function above `build_participant_state()`:

```python
def _build_codereview_for_participant(pid: str) -> dict | None:
    if state.codereview_snippet is None:
        return None
    total_participants = len(participant_ids())
    # Percentages only during reviewing phase
    line_percentages = {}
    if state.codereview_phase == "reviewing" and total_participants > 0:
        line_counts: dict[int, int] = {}
        for selections in state.codereview_selections.values():
            for line in selections:
                line_counts[line] = line_counts.get(line, 0) + 1
        line_percentages = {
            str(line): round(count * 100 / total_participants)
            for line, count in line_counts.items()
        }
    return {
        "snippet": state.codereview_snippet,
        "language": state.codereview_language,
        "phase": state.codereview_phase,
        "my_selections": sorted(state.codereview_selections.get(pid, set())),
        "confirmed_lines": sorted(state.codereview_confirmed),
        "line_percentages": line_percentages,
    }
```

- [ ] **Step 2: Add code review data to `build_host_state()`**

In `build_host_state()`, add the following key to the return dict (after the `qa_questions` line, around line 110):

```python
"codereview": _build_codereview_for_host(),
```

Then add the helper function:

```python
def _build_codereview_for_host() -> dict | None:
    if state.codereview_snippet is None:
        return None
    # Compute line counts
    line_counts: dict[int, int] = {}
    line_pids: dict[int, list[str]] = {}
    for pid, selections in state.codereview_selections.items():
        for line in selections:
            line_counts[line] = line_counts.get(line, 0) + 1
            if line not in line_pids:
                line_pids[line] = []
            line_pids[line].append(pid)

    # Build participant lists per line, sorted by score ascending
    line_participants = {}
    for line, pids in line_pids.items():
        participants = []
        for pid in pids:
            participants.append({
                "uuid": pid,
                "name": state.participant_names.get(pid, "Unknown"),
                "score": state.scores.get(pid, 0),
            })
        participants.sort(key=lambda p: p["score"])
        line_participants[str(line)] = participants

    return {
        "snippet": state.codereview_snippet,
        "language": state.codereview_language,
        "phase": state.codereview_phase,
        "line_counts": {str(k): v for k, v in line_counts.items()},
        "confirmed_lines": sorted(state.codereview_confirmed),
        "line_participants": line_participants,
    }
```

- [ ] **Step 3: Verify server starts and state broadcasts**

Run: `python3 -m uvicorn main:app --port 8000`

Expected: No import errors. Open `http://localhost:8000/` — participant page loads, WebSocket connects.

- [ ] **Step 4: Commit**

```bash
git add messaging.py
git commit -m "feat(codereview): add code review data to participant and host state broadcasts"
```

---

### Task 5: Host HTML Structure

**Files:**
- Modify: `static/host.html:23-27` (tab bar)
- Modify: `static/host.html:99-110` (tab content area)
- Modify: `static/host.html:138-143` (center panel)

- [ ] **Step 1: Add Code Review tab button**

In `static/host.html`, add a new tab button after the Q&A button (line 27):

```html
<button class="tab-btn" id="tab-codereview" onclick="switchTab('codereview')">🔍 Code Review</button>
```

- [ ] **Step 2: Add Code Review tab content div**

After the Q&A tab content div (around line 110), add:

```html
<!-- Code Review Tab -->
<div id="tab-content-codereview" style="display:none" class="tab-content">
  <!-- Create state -->
  <div id="codereview-create">
    <div style="display:flex; gap:8px; align-items:center; margin-bottom:8px;">
      <span style="font-weight:600;">New Code Review</span>
      <select id="codereview-language">
        <option value="">Auto-detect</option>
        <option value="java">Java</option>
        <option value="python">Python</option>
        <option value="javascript">JavaScript</option>
        <option value="typescript">TypeScript</option>
        <option value="sql">SQL</option>
        <option value="go">Go</option>
        <option value="csharp">C#</option>
        <option value="kotlin">Kotlin</option>
        <option value="bash">Bash</option>
      </select>
    </div>
    <textarea id="codereview-snippet" placeholder="Paste your code snippet here (10-50 lines)..." rows="12" style="width:100%; font-family:monospace; font-size:13px;"></textarea>
    <div style="display:flex; justify-content:flex-end; margin-top:8px;">
      <button class="btn btn-accent" onclick="startCodeReview()">Start Code Review</button>
    </div>
  </div>
  <!-- Active state (selecting + reviewing) -->
  <div id="codereview-active" style="display:none;">
    <div id="codereview-status-bar" style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
      <span id="codereview-phase-label"></span>
      <div>
        <button id="codereview-close-btn" class="btn btn-danger" onclick="closeCodeReviewSelection()" style="display:none;">Close Selection</button>
        <button id="codereview-clear-btn" class="btn btn-muted" onclick="clearCodeReview()">Clear</button>
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Add Code Review center panel div**

After the Q&A center panel div (around line 143), add:

```html
<div id="center-codereview" style="display:none" class="center-section">
  <div style="display:flex; height:100%;">
    <div id="codereview-code-panel" style="flex:2; overflow:auto; padding:12px;"></div>
    <div style="flex:0 0 1px; background:var(--border);"></div>
    <div id="codereview-side-panel" style="flex:1; overflow:auto; padding:12px;">
      <div class="muted" style="text-align:center; margin-top:40px;">Click a line to see details</div>
    </div>
  </div>
</div>
```

- [ ] **Step 4: Add highlight.js CDN links**

In `static/host.html`, add before the existing `<script>` tags:

```html
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/atom-one-dark.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
```

- [ ] **Step 5: Commit**

```bash
git add static/host.html
git commit -m "feat(codereview): add host HTML structure for Code Review tab and center panel"
```

---

### Task 6: Host JavaScript Logic

**Files:**
- Modify: `static/host.js`

This is the largest frontend task. It covers: tab switching, state rendering, heatmap, side panel, and action buttons.

- [ ] **Step 1: Extend `switchTab()` and `updateCenterPanel()`**

In `static/host.js`, find `switchTab()` (around line 836). The existing `switchTab()` POSTs to `/api/activity` with the tab name — since Task 1 added `CODEREVIEW = "codereview"` to the `ActivityType` enum and `routers/activity.py` accepts any valid `ActivityType` value, this will work automatically. Add the codereview tab toggle:

```javascript
document.getElementById('tab-codereview').classList.toggle('active', tab === 'codereview');
document.getElementById('tab-content-codereview').style.display = tab === 'codereview' ? '' : 'none';
```

In `updateCenterPanel()` (around line 852), add:

```javascript
document.getElementById('center-codereview').style.display = currentActivity === 'codereview' ? '' : 'none';
```

And add the tab sync line:

```javascript
document.getElementById('tab-codereview').classList.toggle('active', currentActivity === 'codereview');
```

- [ ] **Step 2: Add state handler branch for codereview**

In the `msg.type === 'state'` handler (around line 157), after the Q&A rendering block, add:

```javascript
if (currentActivity === 'codereview' && msg.codereview) {
    renderHostCodeReview(msg.codereview);
}
```

- [ ] **Step 3: Add `renderHostCodeReview()` function**

Append the following function to `host.js`:

```javascript
let codereviewSelectedLine = null;

function renderHostCodeReview(cr) {
    const createDiv = document.getElementById('codereview-create');
    const activeDiv = document.getElementById('codereview-active');

    if (cr.phase === 'idle') {
        createDiv.style.display = '';
        activeDiv.style.display = 'none';
        document.getElementById('codereview-code-panel').innerHTML = '';
        document.getElementById('codereview-side-panel').innerHTML =
            '<div class="muted" style="text-align:center;margin-top:40px;">Click a line to see details</div>';
        return;
    }

    createDiv.style.display = 'none';
    activeDiv.style.display = '';

    const closeBtn = document.getElementById('codereview-close-btn');
    const phaseLabel = document.getElementById('codereview-phase-label');

    if (cr.phase === 'selecting') {
        closeBtn.style.display = '';
        phaseLabel.innerHTML = '<span style="color:var(--accent2);">● Selection open</span>';
    } else {
        closeBtn.style.display = 'none';
        const confirmedCount = cr.confirmed_lines ? cr.confirmed_lines.length : 0;
        phaseLabel.innerHTML = `<span style="color:var(--warn);">Review mode — ${confirmedCount} line(s) confirmed</span>`;
    }

    renderHostCodePanel(cr);
    renderHostSidePanel(cr);
}
```

- [ ] **Step 4: Add `renderHostCodePanel()` — heatmap code view**

```javascript
function renderHostCodePanel(cr) {
    const panel = document.getElementById('codereview-code-panel');
    const lines = cr.snippet.split('\n');
    const lineCounts = cr.line_counts || {};
    const confirmed = new Set(cr.confirmed_lines || []);

    // Find max count for heatmap scaling
    const maxCount = Math.max(1, ...Object.values(lineCounts));

    let html = '<div class="codereview-lines">';
    lines.forEach((lineText, i) => {
        const lineNum = i + 1;
        const count = lineCounts[String(lineNum)] || 0;
        const intensity = count / maxCount;
        const isConfirmed = confirmed.has(lineNum);
        const isSelected = codereviewSelectedLine === lineNum;

        let bgColor, borderColor, gutterText;
        if (isConfirmed) {
            bgColor = `rgba(166,227,161,0.2)`;
            borderColor = 'var(--accent2)';
            gutterText = `${lineNum} ✓`;
        } else if (isSelected) {
            bgColor = `rgba(108,99,255,0.25)`;
            borderColor = 'var(--accent)';
            gutterText = `${lineNum} ▶`;
        } else {
            bgColor = `rgba(255,80,80,${intensity * 0.7})`;
            borderColor = 'transparent';
            gutterText = String(lineNum);
        }

        const clickable = cr.phase === 'reviewing' && !isConfirmed ? 'codereview-line-clickable' : '';

        html += `<div class="codereview-line ${clickable}" style="background:${bgColor};border-left:3px solid ${borderColor};" onclick="selectCodeReviewLine(${lineNum})">`;
        html += `<span class="codereview-gutter">${gutterText}</span>`;
        html += `<span class="codereview-code">${escHtml(lineText) || ' '}</span>`;
        if (count > 0) {
            const countColor = isConfirmed ? 'var(--accent2)' : 'var(--danger)';
            html += `<span class="codereview-count" style="color:${countColor}">${count}</span>`;
        }
        html += `</div>`;
    });
    html += '</div>';

    panel.innerHTML = html;
}
```

- [ ] **Step 5: Add `selectCodeReviewLine()` and `renderHostSidePanel()`**

```javascript
function selectCodeReviewLine(lineNum) {
    codereviewSelectedLine = lineNum;
    // Re-render with current state — the state handler will re-call renderHostCodeReview
    // But we need immediate feedback, so update side panel from last known state
    const lastState = window._lastCodereviewState;
    if (lastState) {
        renderHostCodePanel(lastState);
        renderHostSidePanel(lastState);
    }
}

function renderHostSidePanel(cr) {
    const panel = document.getElementById('codereview-side-panel');
    const confirmed = new Set(cr.confirmed_lines || []);

    if (codereviewSelectedLine === null) {
        panel.innerHTML = '<div class="muted" style="text-align:center;margin-top:40px;">Click a line to see details</div>';
        return;
    }

    const lineNum = codereviewSelectedLine;
    const lineParticipants = (cr.line_participants || {})[String(lineNum)] || [];
    const count = (cr.line_counts || {})[String(lineNum)] || 0;
    const isConfirmed = confirmed.has(lineNum);
    const snippetLines = cr.snippet.split('\n');
    const lineText = snippetLines[lineNum - 1] || '';

    let html = `<div style="margin-bottom:12px;">`;
    html += `<div style="font-weight:600;color:${isConfirmed ? 'var(--accent2)' : 'var(--danger)'};">Line ${lineNum} — ${count} selection(s)</div>`;
    html += `<div class="muted" style="font-size:11px;font-family:monospace;margin-top:4px;">${escHtml(lineText.trim())}</div>`;
    html += `</div>`;

    if (lineParticipants.length > 0) {
        html += '<div class="codereview-participant-list">';
        lineParticipants.forEach(p => {
            html += `<div class="codereview-participant-row">`;
            html += `<span class="codereview-participant-score">${p.score}</span>`;
            html += `<span>${escHtml(p.name)}</span>`;
            html += `</div>`;
        });
        html += '</div>';
    } else {
        html += '<div class="muted">No participants selected this line</div>';
    }

    if (cr.phase === 'reviewing' && !isConfirmed && count > 0) {
        html += `<button class="btn btn-accent" style="width:100%;margin-top:12px;" onclick="confirmCodeReviewLine(${lineNum})">✓ Confirm Line (award 200 pts)</button>`;
    }
    if (isConfirmed) {
        html += `<div style="text-align:center;margin-top:12px;color:var(--accent2);font-weight:600;">✓ Confirmed</div>`;
    }

    panel.innerHTML = html;
}
```

- [ ] **Step 6: Add action functions and state caching**

```javascript
// Cache last codereview state for side panel re-renders
window._lastCodereviewState = null;

async function startCodeReview() {
    const snippet = document.getElementById('codereview-snippet').value;
    const langSelect = document.getElementById('codereview-language');
    const language = langSelect.value || null;

    if (!snippet.trim()) return alert('Please paste a code snippet');

    await fetch('/api/codereview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ snippet, language }),
    });
}

async function closeCodeReviewSelection() {
    await fetch('/api/codereview/status', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ open: false }),
    });
}

async function confirmCodeReviewLine(line) {
    await fetch('/api/codereview/confirm-line', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ line }),
    });
}

async function clearCodeReview() {
    codereviewSelectedLine = null;
    await fetch('/api/codereview', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
    });
}
```

Also, update the `renderHostCodeReview()` function to cache state. Add this line at the top of the function body:

```javascript
window._lastCodereviewState = cr;
```

- [ ] **Step 7: Commit**

```bash
git add static/host.js
git commit -m "feat(codereview): add host JS logic for code review tab, heatmap, and side panel"
```

---

### Task 7: Host CSS

**Files:**
- Modify: `static/host.css` (append at end, currently ~line 703)

- [ ] **Step 1: Add code review styles**

Append to `static/host.css`:

```css
/* Code Review */
.codereview-lines {
    font-family: monospace;
    font-size: 13px;
    line-height: 2;
    background: var(--surface);
    border-radius: var(--radius);
    overflow: hidden;
}

.codereview-line {
    display: flex;
    padding: 2px 12px;
    transition: background 0.15s;
}

.codereview-line-clickable {
    cursor: pointer;
}

.codereview-line-clickable:hover {
    filter: brightness(1.2);
}

.codereview-gutter {
    width: 32px;
    text-align: right;
    margin-right: 12px;
    color: var(--muted);
    user-select: none;
    flex-shrink: 0;
}

.codereview-code {
    flex: 1;
    white-space: pre;
    overflow-x: auto;
}

.codereview-count {
    margin-left: 8px;
    font-size: 11px;
    white-space: nowrap;
    flex-shrink: 0;
}

.codereview-participant-list {
    font-size: 13px;
    line-height: 2;
}

.codereview-participant-row {
    display: flex;
    gap: 8px;
    padding: 4px 0;
    border-bottom: 1px solid var(--border);
}

.codereview-participant-score {
    color: var(--warn);
    min-width: 48px;
}
```

- [ ] **Step 2: Commit**

```bash
git add static/host.css
git commit -m "feat(codereview): add host CSS for heatmap, side panel, and participant list"
```

---

### Task 8: Participant HTML — highlight.js CDN

**Files:**
- Modify: `static/participant.html:50-55` (script loading area)

- [ ] **Step 1: Add highlight.js CDN links**

In `static/participant.html`, add before the existing `<script>` tags (around line 50):

```html
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/atom-one-dark.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
```

- [ ] **Step 2: Commit**

```bash
git add static/participant.html
git commit -m "feat(codereview): add highlight.js CDN to participant page"
```

---

### Task 9: Participant JavaScript — Code Review Screen

**Files:**
- Modify: `static/participant.js`

- [ ] **Step 1: Add codereview branch to `handleMessage()`**

In `static/participant.js`, find the activity routing in `handleMessage()` (around lines 317-327). Add before the `else` fallback:

```javascript
} else if (msg.current_activity === 'codereview') {
    renderCodeReviewScreen(msg.codereview);
```

- [ ] **Step 2: Add `renderCodeReviewScreen()` function**

Append to `participant.js`:

```javascript
let codereviewMySelections = new Set();

function renderCodeReviewScreen(cr) {
    if (!cr) return;

    const content = document.getElementById('content');
    codereviewMySelections = new Set(cr.my_selections || []);
    const confirmed = new Set(cr.confirmed_lines || []);
    const isSelecting = cr.phase === 'selecting';
    const isReviewing = cr.phase === 'reviewing';
    const lines = cr.snippet.split('\n');
    const percentages = cr.line_percentages || {};

    let html = '<div class="codereview-screen">';
    html += '<div class="codereview-header">📝 Code Review</div>';
    html += `<div class="codereview-subtitle">${isSelecting ? 'Click on lines that contain issues' : 'Selection closed — reviewing results'}</div>`;

    html += '<div class="codereview-viewer">';
    lines.forEach((lineText, i) => {
        const lineNum = i + 1;
        const isMine = codereviewMySelections.has(lineNum);
        const isConfirmed = confirmed.has(lineNum);
        const pct = percentages[String(lineNum)];

        let lineClass = 'codereview-pline';
        let gutterContent = String(lineNum);
        let badge = '';

        if (isConfirmed && isMine) {
            lineClass += ' codereview-pline-correct';
            gutterContent = `${lineNum} ✓`;
            badge = '<span class="codereview-badge codereview-badge-correct">+200</span>';
        } else if (isConfirmed && !isMine) {
            lineClass += ' codereview-pline-confirmed';
            gutterContent = `${lineNum} ✓`;
        } else if (isMine) {
            lineClass += ' codereview-pline-selected';
            gutterContent = `${lineNum} ●`;
        }

        if (isSelecting) {
            lineClass += ' codereview-pline-clickable';
        }

        const pctBadge = isReviewing && pct !== undefined ? `<span class="codereview-pct">${pct}%</span>` : '';

        html += `<div class="${lineClass}" onclick="toggleCodeReviewLine(${lineNum})">`;
        html += `<span class="codereview-pgutter">${gutterContent}</span>`;
        html += `<span class="codereview-pcode">${escHtml(lineText) || ' '}</span>`;
        html += badge;
        html += pctBadge;
        html += `</div>`;
    });
    html += '</div>';

    // Selection counter or score summary
    if (isSelecting) {
        html += `<div class="codereview-footer">You selected ${codereviewMySelections.size} line(s)</div>`;
    } else if (isReviewing) {
        const pointsEarned = [...confirmed].filter(l => codereviewMySelections.has(l)).length * 200;
        if (pointsEarned > 0) {
            html += `<div class="codereview-footer codereview-footer-points"><span class="codereview-points-earned">+${pointsEarned}</span> points earned</div>`;
        }
    }

    html += '</div>';
    content.innerHTML = html;

    // Apply syntax highlighting as a single block for consistent tokens
    if (typeof hljs !== 'undefined') {
        const codeBlock = document.createElement('code');
        codeBlock.textContent = cr.snippet;
        if (cr.language) {
            codeBlock.className = `language-${cr.language}`;
        }
        const pre = document.createElement('pre');
        pre.appendChild(codeBlock);
        hljs.highlightElement(codeBlock);

        // Now split highlighted HTML back into lines
        const highlightedLines = codeBlock.innerHTML.split('\n');
        content.querySelectorAll('.codereview-pcode').forEach((el, i) => {
            if (highlightedLines[i] !== undefined) {
                el.innerHTML = highlightedLines[i] || ' ';
            }
        });
    }
}
```

- [ ] **Step 3: Add `toggleCodeReviewLine()` function**

```javascript
function toggleCodeReviewLine(lineNum) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;

    if (codereviewMySelections.has(lineNum)) {
        ws.send(JSON.stringify({ type: 'codereview_deselect', line: lineNum }));
    } else {
        ws.send(JSON.stringify({ type: 'codereview_select', line: lineNum }));
    }
}
```

- [ ] **Step 4: Check for `escHtml` utility**

Verify the function name used in `participant.js` for HTML escaping. The existing code likely uses `escHtml()`. If the name differs, update `renderCodeReviewScreen()` accordingly.

- [ ] **Step 5: Commit**

```bash
git add static/participant.js
git commit -m "feat(codereview): add participant JS for code review screen with line selection and review"
```

---

### Task 10: Participant CSS

**Files:**
- Modify: `static/participant.css` (append at end, currently ~line 460)

- [ ] **Step 1: Add code review styles**

Append to `static/participant.css`:

```css
/* Code Review */
.codereview-screen {
    padding: 16px;
}

.codereview-header {
    font-size: 15px;
    font-weight: 600;
    color: var(--text);
    margin-bottom: 4px;
}

.codereview-subtitle {
    font-size: 13px;
    color: var(--muted);
    margin-bottom: 16px;
}

.codereview-viewer {
    font-family: monospace;
    font-size: 13px;
    line-height: 2.2;
    background: var(--surface);
    border-radius: var(--radius);
    overflow: hidden;
}

.codereview-pline {
    display: flex;
    padding: 3px 12px;
    transition: background 0.15s;
}

.codereview-pline-clickable {
    cursor: pointer;
}

.codereview-pline-clickable:hover {
    background: rgba(255, 255, 255, 0.03);
}

.codereview-pline-selected {
    background: rgba(108, 99, 255, 0.15);
    border-left: 3px solid var(--accent);
}

.codereview-pline-correct {
    background: rgba(166, 227, 161, 0.2);
    border-left: 3px solid #a6e3a1;
}

.codereview-pline-confirmed {
    background: rgba(166, 227, 161, 0.1);
    border-left: 3px solid #a6e3a1;
}

.codereview-pgutter {
    width: 32px;
    text-align: right;
    margin-right: 14px;
    color: var(--muted);
    user-select: none;
    flex-shrink: 0;
}

.codereview-pline-selected .codereview-pgutter {
    color: var(--accent);
}

.codereview-pline-correct .codereview-pgutter,
.codereview-pline-confirmed .codereview-pgutter {
    color: #a6e3a1;
}

.codereview-pcode {
    flex: 1;
    white-space: pre;
    overflow-x: auto;
}

.codereview-badge {
    margin-left: 8px;
    font-size: 11px;
    white-space: nowrap;
    flex-shrink: 0;
}

.codereview-badge-correct {
    color: #a6e3a1;
    font-weight: 600;
}

.codereview-pct {
    margin-left: 8px;
    font-size: 11px;
    color: var(--muted);
    white-space: nowrap;
    flex-shrink: 0;
}

.codereview-footer {
    margin-top: 12px;
    text-align: center;
    color: var(--muted);
    font-size: 13px;
}

.codereview-footer-points {
    padding: 10px;
    background: var(--surface);
    border-radius: var(--radius);
}

.codereview-points-earned {
    color: #a6e3a1;
    font-size: 14px;
    font-weight: 600;
}
```

- [ ] **Step 2: Commit**

```bash
git add static/participant.css
git commit -m "feat(codereview): add participant CSS for code review screen"
```

---

### Task 11: Integration Testing & Polish

**Files:**
- All files from previous tasks

This task validates the full end-to-end flow.

- [ ] **Step 1: Start the server**

```bash
python3 -m uvicorn main:app --reload --port 8000
```

- [ ] **Step 2: Test create flow**

1. Open `http://localhost:8000/host` — verify Code Review tab appears
2. Click the Code Review tab
3. Paste a Java snippet into the text area
4. Select "Java" from the language dropdown
5. Click "Start Code Review"
6. Verify: snippet appears in the center panel with heatmap (all lines at 0)

- [ ] **Step 3: Test participant selection**

1. Open `http://localhost:8000/` in another browser tab
2. Set a participant name
3. Verify: code snippet appears with syntax highlighting
4. Click a few lines — verify they highlight blue with ● marker
5. Click a selected line — verify it deselects (toggle)
6. On host panel: verify heatmap updates in real-time showing selection counts

- [ ] **Step 4: Test close selection**

1. On host panel: click "Close Selection"
2. Verify on participant: lines are no longer clickable, percentage badges appear
3. Verify on host: "Review mode" label shown, lines are clickable for confirm

- [ ] **Step 5: Test confirm flow**

1. On host: click a line that has selections
2. Verify side panel shows participant list sorted by score ascending, with "Confirm Line" button
3. Click "Confirm Line"
4. Verify on host: line turns green with ✓
5. Verify on participant: line turns green, "+200 pts" badge appears if they selected it
6. Verify participant score updated

- [ ] **Step 6: Test clear**

1. On host: click "Clear"
2. Verify: code review is cleared, activity returns to none, participant sees idle screen

- [ ] **Step 7: Fix any issues found during testing**

Address any bugs, styling issues, or interaction problems discovered in steps 2-6.

- [ ] **Step 8: Take screenshots of both host and participant views**

Capture screenshots showing:
- Host view during selecting phase (with heatmap)
- Host view during review phase (with side panel and confirmed line)
- Participant view during selecting phase
- Participant view during review phase (with percentages and green confirmed line)

- [ ] **Step 9: Commit any fixes**

```bash
git add -A
git commit -m "fix(codereview): integration fixes from end-to-end testing"
```

---

### Task 12: Update Architecture Diagrams

**Files:**
- Modify: `adoc/c4_c3_components.puml` (add codereview router component)

- [ ] **Step 1: Read current C4 C3 diagram**

Read `adoc/c4_c3_components.puml` to understand the current component structure.

- [ ] **Step 2: Add codereview router component**

Add a new component for the codereview router, following the pattern of existing activity routers (poll, wordcloud, qa).

- [ ] **Step 3: Commit**

```bash
git add adoc/c4_c3_components.puml
git commit -m "docs: update C3 component diagram with Code Review router"
```

---

### Task 13: Update CLAUDE.md and Backlog

**Files:**
- Modify: `CLAUDE.md` (update AppState model, auth scope, project structure if needed)
- Modify: `backlog.md` (mark Code Review activity as done)

- [ ] **Step 1: Update CLAUDE.md**

Add `codereview` fields to the AppState model section. Add `/api/codereview`, `/api/codereview/status`, `/api/codereview/confirm-line` to the host auth scope. Add code review to the Interaction Features section.

- [ ] **Step 2: Update backlog.md**

Add an entry for the Code Review activity as completed.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md backlog.md
git commit -m "docs: update CLAUDE.md and backlog with Code Review activity"
```
