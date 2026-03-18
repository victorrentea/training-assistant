# Word Cloud Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a live word cloud activity where participants submit words that form an animated D3-cloud word cloud on all screens, with the host controlling open/close and the host UI redesigned into a 3-column layout.

**Architecture:** New `ActivityType` enum + `current_activity` / `wordcloud_words` fields on `AppState`; new `routers/wordcloud.py` HTTP router; `wordcloud_word` WS message handled in `routers/ws.py`; `messaging.py` includes the new fields in every state broadcast. Host UI is redesigned into a 3-column layout (controls | activity | participants); participant UI adds a word cloud screen beside the existing poll/idle screens.

**Tech Stack:** Python/FastAPI (backend), Vanilla JS/HTML/CSS (frontend), D3 v7 + d3-cloud v1 (word cloud rendering via CDN), pytest + FastAPI TestClient (unit tests), Playwright (E2E tests).

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `state.py` | Modify | Add `ActivityType` enum, `current_activity`, `wordcloud_words` fields |
| `messaging.py` | Modify | Include `current_activity` + `wordcloud_words` in `build_state_message()` |
| `routers/wordcloud.py` | **Create** | `POST /api/wordcloud/status` — open/close word cloud activity |
| `routers/poll.py` | Modify | Return 409 when creating poll if `current_activity != NONE`; set/clear `current_activity` on create/delete |
| `routers/ws.py` | Modify | Handle `wordcloud_word` message type |
| `main.py` | Modify | Register `wordcloud` router |
| `static/host.html` | Modify | 3-column layout; add Word Cloud tab, center activity panel, move participants to right column |
| `static/host.js` | Modify | Handle `current_activity` in state; word cloud tab logic; D3-cloud rendering; PNG download on close |
| `static/host.css` | Modify | 3-column grid styles; word cloud tab styles |
| `static/participant.js` | Modify | Handle `current_activity === "wordcloud"` state; word cloud screen; send `wordcloud_word` WS message |
| `static/participant.html` | No change | `#content` div already hosts dynamic screens |
| `static/participant.css` | Modify | Word cloud screen layout (desktop side-by-side, mobile stacked) |
| `test_main.py` | Modify | Add word cloud DSL helpers + unit tests |
| `test_e2e.py` | Modify | Add E2E tests for word cloud flow |

---

## Task 1: Backend state — ActivityType enum + new AppState fields

**Files:**
- Modify: `state.py`

- [ ] **Step 1: Add `ActivityType` enum and new fields to `AppState`**

In `state.py`, add after the imports:

```python
from enum import Enum

class ActivityType(str, Enum):
    NONE = "none"
    POLL = "poll"
    WORDCLOUD = "wordcloud"
```

In `AppState.reset()`, add these two lines alongside the existing `self.poll`, `self.scores`, etc.:
```python
self.current_activity: ActivityType = ActivityType.NONE
self.wordcloud_words: dict[str, int] = {}
```

`AppState.__init__` calls `self.reset()`, so adding fields in `reset()` is sufficient — no separate `__init__` changes needed. Use `dict[str, int]` (lowercase) for Python 3.9 compatibility.

- [ ] **Step 2: Run existing tests to confirm nothing broke**

```bash
cd /Users/victorrentea/PycharmProjects/training-assistant
pytest test_main.py -v -x
```
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add state.py
git commit -m "feat: add ActivityType enum and wordcloud state fields"
```

---

## Task 2: messaging.py — broadcast current_activity and wordcloud_words

**Files:**
- Modify: `messaging.py`

- [ ] **Step 1: Add `current_activity` and `wordcloud_words` to `build_state_message()`**

In `messaging.py`, inside the `return { ... }` dict of `build_state_message()`, add:
```python
"current_activity": state.current_activity,
"wordcloud_words": state.wordcloud_words,
```

- [ ] **Step 2: Run existing tests**

```bash
pytest test_main.py -v -x
```
Expected: all pass (the new fields are just extra keys in the state message).

- [ ] **Step 3: Commit**

```bash
git add messaging.py
git commit -m "feat: include current_activity and wordcloud_words in state broadcast"
```

---

## Task 3: routers/wordcloud.py — open/close word cloud endpoint

**Files:**
- Create: `routers/wordcloud.py`

- [ ] **Step 1: Write the failing tests first**

In `test_main.py`, add these tests after the existing poll tests. First add DSL helpers to `WorkshopSession`:

```python
def open_wordcloud(self):
    resp = self._client.post("/api/wordcloud/status", json={"active": True})
    assert resp.status_code == 200, f"open_wordcloud failed: {resp.text}"

def close_wordcloud(self):
    resp = self._client.post("/api/wordcloud/status", json={"active": False})
    assert resp.status_code == 200, f"close_wordcloud failed: {resp.text}"

def assert_activity(self, expected: str):
    from state import state
    assert state.current_activity == expected, (
        f"current_activity={state.current_activity!r}, expected {expected!r}"
    )
```

Then add these test functions:

```python
def test_open_wordcloud_sets_activity():
    state.reset()
    session = WorkshopSession()
    session.open_wordcloud()
    session.assert_activity("wordcloud")

def test_close_wordcloud_sets_activity_none():
    state.reset()
    session = WorkshopSession()
    session.open_wordcloud()
    session.close_wordcloud()
    session.assert_activity("none")

def test_open_wordcloud_clears_previous_words():
    state.reset()
    state.wordcloud_words = {"hello": 3}
    session = WorkshopSession()
    session.open_wordcloud()
    assert state.wordcloud_words == {}

def test_open_wordcloud_blocked_when_poll_active():
    state.reset()
    session = WorkshopSession()
    session.create_poll("Q?", ["A", "B"])
    resp = session._client.post("/api/wordcloud/status", json={"active": True})
    assert resp.status_code == 409

def test_create_poll_blocked_when_wordcloud_active():
    state.reset()
    session = WorkshopSession()
    session.open_wordcloud()
    resp = session._client.post("/api/poll", json={"question": "Q?", "options": ["A", "B"]})
    assert resp.status_code == 409
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest test_main.py::test_open_wordcloud_sets_activity \
       test_main.py::test_close_wordcloud_sets_activity_none \
       test_main.py::test_open_wordcloud_clears_previous_words \
       test_main.py::test_open_wordcloud_blocked_when_poll_active \
       test_main.py::test_create_poll_blocked_when_wordcloud_active -v
```
Expected: all FAIL (404/ImportError — router not registered yet).

- [ ] **Step 3: Create `routers/wordcloud.py`**

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from messaging import broadcast, build_state_message
from state import state, ActivityType

router = APIRouter()


class WordCloudStatus(BaseModel):
    active: bool


@router.post("/api/wordcloud/status")
async def set_wordcloud_status(body: WordCloudStatus):
    if body.active:
        if state.current_activity != ActivityType.NONE:
            raise HTTPException(409, "Another activity is already active")
        state.current_activity = ActivityType.WORDCLOUD
        state.wordcloud_words = {}
    else:
        state.current_activity = ActivityType.NONE
    await broadcast(build_state_message())
    return {"ok": True}
```

- [ ] **Step 4: Register router in `main.py`**

In `main.py`, add:
```python
from routers import ws, poll, scores, quiz, pages, wordcloud
# ...
app.include_router(wordcloud.router)
```

- [ ] **Step 5: Add mutual exclusivity to `routers/poll.py`**

In `create_poll()`, before setting `state.poll`, add:
```python
if state.current_activity != ActivityType.NONE:
    raise HTTPException(409, "Another activity is already active")
```

On `create_poll` success, add:
```python
state.current_activity = ActivityType.POLL
```

In `clear_poll()`, add:
```python
state.current_activity = ActivityType.NONE
```

Add the import at the top of `poll.py`:
```python
from state import state, ActivityType
```
(replace the existing `from state import state`)

- [ ] **Step 6: Run the new tests**

```bash
pytest test_main.py::test_open_wordcloud_sets_activity \
       test_main.py::test_close_wordcloud_sets_activity_none \
       test_main.py::test_open_wordcloud_clears_previous_words \
       test_main.py::test_open_wordcloud_blocked_when_poll_active \
       test_main.py::test_create_poll_blocked_when_wordcloud_active -v
```
Expected: all PASS.

- [ ] **Step 7: Run full suite**

```bash
pytest test_main.py -v
```
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add routers/wordcloud.py routers/poll.py main.py test_main.py
git commit -m "feat: add wordcloud open/close endpoint + mutual exclusivity with polls"
```

---

## Task 4: WebSocket — handle wordcloud_word message

**Files:**
- Modify: `routers/ws.py`
- Modify: `test_main.py`

- [ ] **Step 1: Write the failing tests**

Add DSL helper to `ParticipantSession`:

```python
def submit_word(self, word: str):
    self.send({"type": "wordcloud_word", "word": word})
    self._last_state = self._recv("state")

def assert_wordcloud_word(self, word: str, expected_count: int):
    words = self._last_state.get("wordcloud_words", {})
    actual = words.get(word, 0)
    assert actual == expected_count, (
        f"{self.name}: wordcloud_words[{word!r}]={actual}, expected {expected_count}"
    )
```

Add test functions:

```python
def test_wordcloud_word_increments_count():
    state.reset()
    session = WorkshopSession()
    session.open_wordcloud()
    client = TestClient(app)
    with client.websocket_connect("/ws/Alice") as ws_alice:
        alice = ParticipantSession(ws_alice, "Alice")
        alice.submit_word("microservices")
        alice.assert_wordcloud_word("microservices", 1)
        alice.submit_word("microservices")
        alice.assert_wordcloud_word("microservices", 2)

def test_wordcloud_word_normalizes():
    state.reset()
    session = WorkshopSession()
    session.open_wordcloud()
    client = TestClient(app)
    with client.websocket_connect("/ws/Alice") as ws_alice:
        alice = ParticipantSession(ws_alice, "Alice")
        alice.submit_word("  Microservices  ")
        alice.assert_wordcloud_word("microservices", 1)

def test_wordcloud_word_awards_200_pts():
    state.reset()
    session = WorkshopSession()
    session.open_wordcloud()
    client = TestClient(app)
    with client.websocket_connect("/ws/Alice") as ws_alice:
        alice = ParticipantSession(ws_alice, "Alice")
        alice.submit_word("complexity")
        alice.assert_score(200)

def test_wordcloud_word_host_gets_no_pts():
    state.reset()
    session = WorkshopSession()
    session.open_wordcloud()
    client = TestClient(app)
    with client.websocket_connect("/ws/__host__") as ws_host:
        host = ParticipantSession(ws_host, "__host__")
        host.submit_word("complexity")
        assert state.scores.get("__host__", 0) == 0

def test_wordcloud_word_rejected_when_not_active():
    state.reset()
    session = WorkshopSession()
    # wordcloud NOT opened
    client = TestClient(app)
    with client.websocket_connect("/ws/Alice") as ws_alice:
        alice = ParticipantSession(ws_alice, "Alice")
        alice.send({"type": "wordcloud_word", "word": "test"})
        # No state update — word should be silently dropped
        assert state.wordcloud_words == {}
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest test_main.py::test_wordcloud_word_increments_count \
       test_main.py::test_wordcloud_word_normalizes \
       test_main.py::test_wordcloud_word_awards_200_pts \
       test_main.py::test_wordcloud_word_host_gets_no_pts \
       test_main.py::test_wordcloud_word_rejected_when_not_active -v
```
Expected: FAIL.

- [ ] **Step 3: Add `wordcloud_word` handler in `routers/ws.py`**

In the `while True:` message dispatch block, add after the `multi_vote` branch:

```python
elif data.get("type") == "wordcloud_word":
    from state import ActivityType
    word = str(data.get("word", "")).strip().lower()
    if state.current_activity == ActivityType.WORDCLOUD and word:
        state.wordcloud_words[word] = state.wordcloud_words.get(word, 0) + 1
        if name != "__host__":
            state.scores[name] = state.scores.get(name, 0) + 200
        await broadcast(build_state_message())
```

- [ ] **Step 4: Run the new tests**

```bash
pytest test_main.py::test_wordcloud_word_increments_count \
       test_main.py::test_wordcloud_word_normalizes \
       test_main.py::test_wordcloud_word_awards_200_pts \
       test_main.py::test_wordcloud_word_host_gets_no_pts \
       test_main.py::test_wordcloud_word_rejected_when_not_active -v
```
Expected: all PASS.

- [ ] **Step 5: Run full test suite**

```bash
pytest test_main.py -v
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add routers/ws.py test_main.py
git commit -m "feat: handle wordcloud_word WS message with scoring"
```

---

## Task 5: Participant UI — word cloud screen

**Files:**
- Modify: `static/participant.js`
- Modify: `static/participant.css`

The participant already has a `#content` div that is replaced with different screens. This task adds the word cloud screen rendered when `current_activity === "wordcloud"`.

- [ ] **Step 1: Add `renderWordCloudScreen()` to `participant.js`**

Find the section in `participant.js` that handles the `state` message and renders different screens (idle / poll). After the existing screen logic, add handling for `current_activity === "wordcloud"`.

Add this function (place near other `render*` functions):

```javascript
let myWords = [];  // participant's own submitted words (session-only, clears on reconnect)

function renderWordCloudScreen(wordcloudWords) {
  const content = document.getElementById('content');
  if (content.dataset.screen !== 'wordcloud') {
    myWords = [];  // reset on fresh entry
    content.dataset.screen = 'wordcloud';
    content.innerHTML = `
      <div class="wc-layout">
        <div class="wc-cloud-panel">
          <canvas id="wc-canvas"></canvas>
        </div>
        <div class="wc-input-panel">
          <p class="wc-prompt">What word comes to mind?</p>
          <div class="wc-input-row">
            <input id="wc-input" type="text" maxlength="40" autocomplete="off" placeholder="Type a word…" />
            <button id="wc-go" class="btn btn-primary">Go</button>
          </div>
          <ul id="wc-my-words"></ul>
        </div>
      </div>`;
    document.getElementById('wc-go').onclick = submitWord;
    document.getElementById('wc-input').addEventListener('keydown', e => {
      if (e.key === 'Enter') submitWord();
    });
  }
  renderWordCloud(wordcloudWords);
  renderMyWords();
}

function submitWord() {
  const input = document.getElementById('wc-input');
  if (!input) return;
  const word = input.value.trim();
  if (!word) return;
  sendWS({ type: 'wordcloud_word', word });
  myWords.unshift(word);
  input.value = '';
  renderMyWords();
}

function renderMyWords() {
  const ul = document.getElementById('wc-my-words');
  if (!ul) return;
  ul.innerHTML = myWords.map(w => `<li>${escHtml(w)}</li>`).join('');
}
```

- [ ] **Step 2: Add word cloud rendering with D3-cloud**

Add D3 CDN scripts to `static/participant.html` `<head>`:

```html
<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/d3-cloud@1/build/d3.layout.cloud.js"></script>
```

Add to `participant.js`:

```javascript
const WC_COLORS = ['#7ecef4','#a78bfa','#34d399','#fbbf24','#f472b6','#60a5fa','#fb923c'];
let _wcDebounceTimer = null;

function renderWordCloud(words) {
  const canvas = document.getElementById('wc-canvas');
  if (!canvas) return;
  clearTimeout(_wcDebounceTimer);
  _wcDebounceTimer = setTimeout(() => _drawCloud(canvas, words), 300);
}

function _drawCloud(canvas, wordsMap) {
  const entries = Object.entries(wordsMap);
  if (!entries.length) {
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    return;
  }
  const W = canvas.parentElement.clientWidth || 400;
  const H = canvas.parentElement.clientHeight || 300;
  canvas.width = W;
  canvas.height = H;

  const maxCount = Math.max(...entries.map(([,c]) => c));
  const minCount = Math.min(...entries.map(([,c]) => c));
  const sizeScale = d3.scaleLinear()
    .domain([minCount, maxCount])
    .range([14, 60]);

  d3.layout.cloud()
    .size([W, H])
    .words(entries.map(([text, count]) => ({ text, size: sizeScale(count) })))
    .padding(4)
    .rotate(() => (Math.random() > 0.5 ? 90 : 0))
    .font('sans-serif')
    .fontSize(d => d.size)
    .on('end', (placed) => {
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, W, H);
      ctx.textAlign = 'center';
      placed.forEach((w, i) => {
        ctx.save();
        ctx.translate(W / 2 + w.x, H / 2 + w.y);
        ctx.rotate((w.rotate * Math.PI) / 180);
        ctx.font = `bold ${w.size}px sans-serif`;
        ctx.fillStyle = WC_COLORS[i % WC_COLORS.length];
        ctx.fillText(w.text, 0, 0);
        ctx.restore();
      });
    })
    .start();
}
```

- [ ] **Step 3: Hook `renderWordCloudScreen` into the state message handler**

In `participant.js`, find where `msg.type === 'state'` is handled and where different screens are shown. Currently it calls something like `renderIdle()` or `renderPoll()`. Add:

```javascript
if (msg.current_activity === 'wordcloud') {
  renderWordCloudScreen(msg.wordcloud_words || {});
} else if (msg.poll) {
  renderPoll(msg);  // existing
} else {
  renderIdle();     // existing
}
```

Also add re-render on word cloud state updates (they arrive as full `state` messages, so the existing `state` handler covers it). When `current_activity` returns to `"none"`, the else branch above restores the idle screen.

- [ ] **Step 4: Add CSS for word cloud layout**

In `static/participant.css`, add:

```css
/* Word Cloud screen */
.wc-layout {
  display: flex;
  gap: 1.5rem;
  align-items: flex-start;
  flex-wrap: wrap;
}

.wc-cloud-panel {
  flex: 1 1 300px;
  min-height: 260px;
  background: var(--surface2);
  border-radius: 10px;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}

.wc-cloud-panel canvas {
  display: block;
  width: 100%;
  height: 100%;
}

.wc-input-panel {
  flex: 0 1 260px;
  display: flex;
  flex-direction: column;
  gap: .75rem;
}

.wc-prompt {
  font-size: 1rem;
  color: var(--text);
  margin: 0;
}

.wc-input-row {
  display: flex;
  gap: .5rem;
}

.wc-input-row input {
  flex: 1;
  padding: .5rem .75rem;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--surface2);
  color: var(--text);
  font-size: 1rem;
}

#wc-my-words {
  list-style: disc;
  padding-left: 1.25rem;
  color: var(--muted);
  font-size: .9rem;
  max-height: 200px;
  overflow-y: auto;
}

/* Mobile: stack cloud on top */
@media (max-width: 600px) {
  .wc-layout {
    flex-direction: column-reverse;
  }
  .wc-cloud-panel {
    width: 100%;
    min-height: 220px;
    order: -1;
  }
  .wc-input-panel {
    width: 100%;
  }
}
```

- [ ] **Step 5: Verify manually in browser**

```bash
cd /Users/victorrentea/PycharmProjects/training-assistant
python3 -m uvicorn main:app --reload --port 8000
```

Open http://localhost:8000/host and http://localhost:8000/ in two tabs. Via the API directly or a temporary curl:
```bash
curl -s -X POST http://localhost:8000/api/wordcloud/status \
  -H 'Content-Type: application/json' -d '{"active": true}'
```

Participant should switch to word cloud screen. Submit a word — cloud should render.

- [ ] **Step 6: Commit**

```bash
git add static/participant.js static/participant.css static/participant.html
git commit -m "feat: participant word cloud screen with D3-cloud rendering"
```

---

## Task 6: Host UI — 3-column layout redesign

**Files:**
- Modify: `static/host.html`
- Modify: `static/host.css`
- Modify: `static/host.js`

This is the largest frontend task. The current card-stack layout becomes a fixed 3-column layout.

**3-column structure:**
- Left (~25%): tab switcher + poll composer OR word cloud controls + status badges
- Center (~50%): state-driven activity panel (QR / poll results / word cloud)
- Right (~25%): participant list + join link + reset scores

- [ ] **Step 1: Rewrite `host.html` structure**

Replace the existing `<div class="grid">` content with the 3-column structure:

```html
<div class="host-columns">

  <!-- LEFT COLUMN: controls -->
  <div class="host-col host-col-left">
    <!-- Tab switcher -->
    <div class="tab-bar">
      <button class="tab-btn active" id="tab-poll" onclick="switchTab('poll')">Poll</button>
      <button class="tab-btn" id="tab-wordcloud" onclick="switchTab('wordcloud')">☁ Word Cloud</button>
    </div>

    <!-- Poll tab content -->
    <div id="tab-content-poll" class="tab-content">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:.6rem; flex-wrap:wrap; gap:.4rem;">
        <div style="display:flex; align-items:center; gap:.5rem; flex-wrap:wrap;">
          <span id="ws-badge" class="badge disconnected">● Server</span>
          <span id="daemon-badge" class="badge disconnected" title="">Agent</span>
        </div>
      </div>
      <div id="poll-input" class="poll-composer" contenteditable="true" spellcheck="false"
           data-placeholder="Question title&#10;&#10;Option A&#10;Option B&#10;Option C"></div>
      <div class="btn-row" style="align-items:center;">
        <button class="btn btn-primary" id="create-btn">🚀 Launch</button>
        <label style="display:flex; align-items:center; gap:.4rem; font-size:.9rem; color:var(--text); cursor:pointer; margin:0;">
          <input type="checkbox" id="multi-check" style="width:1rem; height:1rem; cursor:pointer;" />
          Multi-select
        </label>
        <label id="correct-count-label" style="display:none; align-items:center; gap:.4rem; font-size:.9rem; color:var(--text); margin:0;">
          <input type="number" id="correct-count" min="1" max="8" value="2"
                 style="width:3.2rem; height:34px; box-sizing:border-box; text-align:center; background:var(--surface2); color:var(--text); border:1px solid var(--border); border-radius:6px; font-size:.9rem;" />
          correct
        </label>
      </div>
      <div class="or-divider"><span>or</span></div>
      <div class="quiz-gen-row">
        <div class="quiz-gen-controls">
          <button class="btn btn-warn" id="gen-quiz-btn" onclick="requestQuiz()">🤖 Generate</button>
          <div style="display:flex;align-items:center;gap:.4rem;font-size:.9rem;color:var(--text);">
            from last
            <select id="quiz-minutes" style="background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:.3rem .5rem;font-size:.9rem;cursor:pointer;">
              <option value="15">15 min</option>
              <option value="30" selected>30 min</option>
              <option value="60">1 hour</option>
              <option value="90">1.5 hours</option>
              <option value="480">whole day</option>
            </select>
          </div>
        </div>
        <span id="quiz-status"></span>
      </div>
      <!-- Generated preview (inline in left column) -->
      <div id="preview-card" style="display:none; margin-top:.75rem;">
        <h3 style="margin:0 0 .5rem; font-size:.95rem; color:var(--accent);">🤖 Generated Question</h3>
        <div id="preview-display"></div>
        <div class="btn-row" style="margin-top:.5rem;">
          <button class="btn btn-success" onclick="firePreview()">🚀 Launch</button>
        </div>
      </div>
    </div>

    <!-- Word Cloud tab content -->
    <div id="tab-content-wordcloud" class="tab-content" style="display:none;">
      <div id="wc-inactive">
        <button class="btn btn-primary wc-open-btn" id="wc-open-btn" onclick="openWordCloud()">☁ Open Word Cloud</button>
        <p id="wc-blocked-msg" style="display:none; font-size:.85rem; color:var(--warn); margin-top:.5rem;">Remove the current poll first.</p>
      </div>
      <div id="wc-active" style="display:none;">
        <button class="btn btn-danger" onclick="closeWordCloud()">✕ Close Word Cloud</button>
        <div style="margin-top:.75rem;">
          <div class="wc-input-row">
            <input id="wc-host-input" type="text" maxlength="40" autocomplete="off" placeholder="Submit a word…" />
            <button class="btn btn-primary" onclick="hostSubmitWord()">Go</button>
          </div>
        </div>
        <ul id="wc-host-words" style="margin-top:.5rem; list-style:disc; padding-left:1.25rem; color:var(--muted); font-size:.85rem; max-height:180px; overflow-y:auto;"></ul>
      </div>
    </div>
  </div>

  <!-- CENTER COLUMN: current activity -->
  <div class="host-col host-col-center">
    <!-- QR idle state -->
    <div id="center-qr" class="center-panel">
      <div id="qr-code" class="qr-code" title="Click to enlarge"></div>
    </div>
    <!-- Poll results panel -->
    <div id="center-poll" class="center-panel" style="display:none;">
      <div id="poll-display"></div>
    </div>
    <!-- Word cloud panel -->
    <div id="center-wordcloud" class="center-panel" style="display:none;">
      <canvas id="host-wc-canvas"></canvas>
    </div>
  </div>

  <!-- RIGHT COLUMN: participants -->
  <div class="host-col host-col-right">
    <div class="right-header">
      <div class="stat" id="pax-count">0</div>
      <div class="stat-label">participants</div>
    </div>
    <ul id="pax-list" class="pax-list" title="Click a location to view map"></ul>
    <div class="right-footer">
      <span>Join: <a id="participant-link" style="color:var(--accent); word-break:break-all; font-size:.8rem;" href="/" target="_blank"></a></span>
      <div style="display:flex; gap:.5rem; margin-top:.4rem; flex-wrap:wrap;">
        <button class="btn btn-danger" onclick="resetScores()" title="Reset all scores to zero">↺ Reset scores</button>
        <button class="btn btn-primary" onclick="downloadPollHistory()" title="Download today's polls">⬇ Quiz Q&amp;A</button>
      </div>
    </div>
  </div>

</div>
```

Keep the existing modal overlays (QR overlay, map modal, toast) outside the columns div.

- [ ] **Step 2: Add 3-column CSS to `host.css`**

Add:
```css
/* 3-column host layout */
.host-columns {
  display: grid;
  grid-template-columns: 25% 1fr 25%;
  gap: 1rem;
  height: 100vh;
  padding: 1rem;
  box-sizing: border-box;
  overflow: hidden;
}

.host-col {
  display: flex;
  flex-direction: column;
  gap: .75rem;
  overflow: hidden;
}

.host-col-left {
  overflow-y: auto;
}

.host-col-right {
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.host-col-right .pax-list {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}

.right-header {
  text-align: center;
}

.right-footer {
  margin-top: auto;
  padding-top: .5rem;
  border-top: 1px solid var(--border);
  font-size: .8rem;
  color: var(--muted);
}

/* Center activity panel */
.center-panel {
  width: 100%;
  height: 100%;
}

#center-wordcloud {
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--surface2);
  border-radius: 10px;
  overflow: hidden;
}

#host-wc-canvas {
  width: 100%;
  height: 100%;
  display: block;
}

/* Tabs */
.tab-bar {
  display: flex;
  gap: .25rem;
  border-bottom: 1px solid var(--border);
  margin-bottom: .75rem;
}

.tab-btn {
  padding: .4rem .9rem;
  border: none;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-size: .9rem;
  border-bottom: 2px solid transparent;
  transition: color .15s, border-color .15s;
}

.tab-btn.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}

.tab-btn:hover:not(.active) {
  color: var(--text);
}

.wc-open-btn {
  width: 100%;
  font-size: 1.1rem;
  padding: 1rem;
}

.wc-input-row {
  display: flex;
  gap: .5rem;
}

.wc-input-row input {
  flex: 1;
  padding: .4rem .6rem;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--surface2);
  color: var(--text);
  font-size: .9rem;
}
```

The old layout in `host.html` used `<div class="layout"><div class="grid">` wrappers — replace these with the new `<div class="host-columns">` structure defined above.

In `host.css`, the following rules are now superseded by `.host-columns` and should be removed to avoid conflicts:
- `.layout { max-width: 900px; margin: 0 auto; }` (line 13)
- `.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }` (line 28)
- `@media (max-width: 640px) { .grid { grid-template-columns: 1fr; } }` (line 29)

Also update `body` in `host.css` — remove `padding: 2rem 1rem` (the columns div handles padding now). Keep all other rules (`.card`, `.badge`, `.btn-row`, etc.) as they are still used inside the columns.

- [ ] **Step 3: Add JS functions for word cloud tab and center panel switching**

In `host.js`, add:

```javascript
let hostWords = [];

function switchTab(tab) {
  document.getElementById('tab-poll').classList.toggle('active', tab === 'poll');
  document.getElementById('tab-wordcloud').classList.toggle('active', tab === 'wordcloud');
  document.getElementById('tab-content-poll').style.display = tab === 'poll' ? '' : 'none';
  document.getElementById('tab-content-wordcloud').style.display = tab === 'wordcloud' ? '' : 'none';
}

function updateCenterPanel(currentActivity) {
  document.getElementById('center-qr').style.display = currentActivity === 'none' ? '' : 'none';
  document.getElementById('center-poll').style.display = currentActivity === 'poll' ? '' : 'none';
  document.getElementById('center-wordcloud').style.display = currentActivity === 'wordcloud' ? '' : 'none';
}

async function openWordCloud() {
  const resp = await fetch('/api/wordcloud/status', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ active: true }),
  });
  if (!resp.ok) toast('Cannot open: remove current poll first');
}

async function closeWordCloud() {
  // Trigger PNG download before closing
  const canvas = document.getElementById('host-wc-canvas');
  if (canvas && canvas.width > 0) {
    canvas.toBlob(blob => {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `wordcloud-${new Date().toISOString().slice(0,10)}.png`;
      a.click();
      URL.revokeObjectURL(a.href);
    });
  }
  await fetch('/api/wordcloud/status', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ active: false }),
  });
}

function hostSubmitWord() {
  const input = document.getElementById('wc-host-input');
  if (!input) return;
  const word = input.value.trim();
  if (!word || !ws) return;
  ws.send(JSON.stringify({ type: 'wordcloud_word', word }));
  hostWords.unshift(word);
  input.value = '';
  renderHostWordList();
}

function renderHostWordList() {
  const ul = document.getElementById('wc-host-words');
  if (!ul) return;
  ul.innerHTML = hostWords.map(w => `<li>${escHtml(w)}</li>`).join('');
}

function updateWordCloudTab(currentActivity) {
  const inactive = document.getElementById('wc-inactive');
  const active = document.getElementById('wc-active');
  const blockedMsg = document.getElementById('wc-blocked-msg');
  const openBtn = document.getElementById('wc-open-btn');
  if (!inactive || !active) return;

  const isWordCloudActive = currentActivity === 'wordcloud';
  const isPollActive = currentActivity === 'poll';

  inactive.style.display = isWordCloudActive ? 'none' : '';
  active.style.display = isWordCloudActive ? '' : 'none';

  if (openBtn) {
    openBtn.disabled = isPollActive;
    openBtn.style.opacity = isPollActive ? '.4' : '';
    openBtn.style.cursor = isPollActive ? 'not-allowed' : '';
  }
  if (blockedMsg) {
    blockedMsg.style.display = isPollActive ? '' : 'none';
  }
}
```

- [ ] **Step 4: Update the `state` message handler in `host.js` to use the new panels**

In the `ws.onmessage` handler, where `msg.type === 'state'` is processed, add after existing processing:

```javascript
const currentActivity = msg.current_activity || 'none';
updateCenterPanel(currentActivity);
updateWordCloudTab(currentActivity);

if (currentActivity === 'wordcloud') {
  renderHostWordCloud(msg.wordcloud_words || {});
}

// Move poll display rendering to center-poll div instead of the old full-width card
// renderPollDisplay() already writes to #poll-display — no change needed
```

- [ ] **Step 5: Add host word cloud render function**

```javascript
let _hostWcDebounceTimer = null;

function renderHostWordCloud(wordsMap) {
  const canvas = document.getElementById('host-wc-canvas');
  if (!canvas) return;
  clearTimeout(_hostWcDebounceTimer);
  _hostWcDebounceTimer = setTimeout(() => _drawHostCloud(canvas, wordsMap), 300);
}

function _drawHostCloud(canvas, wordsMap) {
  const entries = Object.entries(wordsMap);
  const container = canvas.parentElement;
  const W = container.clientWidth || 500;
  const H = container.clientHeight || 400;
  canvas.width = W;
  canvas.height = H;
  if (!entries.length) {
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, W, H);
    return;
  }
  const maxCount = Math.max(...entries.map(([,c]) => c));
  const minCount = Math.min(...entries.map(([,c]) => c));
  const sizeScale = d3.scaleLinear().domain([minCount, maxCount]).range([16, 72]);
  d3.layout.cloud()
    .size([W, H])
    .words(entries.map(([text, count]) => ({ text, size: sizeScale(count) })))
    .padding(4)
    .rotate(() => (Math.random() > 0.5 ? 90 : 0))
    .font('sans-serif')
    .fontSize(d => d.size)
    .on('end', (placed) => {
      const WC_COLORS = ['#7ecef4','#a78bfa','#34d399','#fbbf24','#f472b6','#60a5fa','#fb923c'];
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, W, H);
      ctx.textAlign = 'center';
      placed.forEach((w, i) => {
        ctx.save();
        ctx.translate(W/2 + w.x, H/2 + w.y);
        ctx.rotate((w.rotate * Math.PI) / 180);
        ctx.font = `bold ${w.size}px sans-serif`;
        ctx.fillStyle = WC_COLORS[i % WC_COLORS.length];
        ctx.fillText(w.text, 0, 0);
        ctx.restore();
      });
    })
    .start();
}
```

Add D3 CDN scripts to `host.html` `<head>`:
```html
<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/d3-cloud@1/build/d3.layout.cloud.js"></script>
```

Also add Enter key handler for host word input (add after `connectWS()` initializes or in an init function):
```javascript
document.getElementById('wc-host-input')?.addEventListener('keydown', e => {
  if (e.key === 'Enter') hostSubmitWord();
});
```

- [ ] **Step 6: Manual smoke test**

```bash
python3 -m uvicorn main:app --reload --port 8000
```

Open http://localhost:8000/host — verify:
- 3-column layout appears
- QR code shows in center when idle
- Poll tab and Word Cloud tab switch correctly
- Create a poll — center shows poll results, Word Cloud tab button is disabled
- Delete poll — center returns to QR
- Open word cloud — center shows canvas, Word Cloud tab shows Close button
- Submit words from host and from participant — cloud renders
- Close word cloud — PNG download triggers, center returns to QR

- [ ] **Step 7: Commit**

```bash
git add static/host.html static/host.css static/host.js static/participant.html
git commit -m "feat: host 3-column layout with word cloud tab and D3-cloud rendering"
```

---

## Task 7: E2E tests

**Files:**
- Modify: `test_e2e.py`

- [ ] **Step 1: Write E2E tests for word cloud flow**

In `test_e2e.py`, add:

```python
@pytest.fixture()
def participant_page(server_url, playwright):
    browser = playwright.chromium.launch()
    ctx = browser.new_context(base_url=server_url)
    page = ctx.new_page()
    page.goto("/")
    yield page
    ctx.close()
    browser.close()


def test_host_opens_wordcloud_participant_sees_screen(server_url, host_page, participant_page):
    # Participant joins first — wait for idle/main screen to confirm WS is connected
    participant_page.fill('#name-input', 'Tester')
    participant_page.click('#join-btn')
    # Wait for the main screen content div to appear (confirms WS connection established)
    participant_page.wait_for_selector('#main-screen', timeout=5000)
    # Small grace period for WS to receive initial state
    participant_page.wait_for_timeout(500)

    # Host opens word cloud via API (avoids needing host auth in browser)
    import requests
    resp = requests.post(f"{server_url}/api/wordcloud/status", json={"active": True})
    assert resp.status_code == 200

    # Participant sees word cloud screen
    participant_page.wait_for_selector('#wc-canvas', timeout=5000)


def test_participant_submits_word_appears_in_state(server_url, participant_page):
    import requests
    requests.post(f"{server_url}/api/wordcloud/status", json={"active": True})

    participant_page.fill('#name-input', 'WordTester')
    participant_page.click('#join-btn')
    participant_page.wait_for_selector('#wc-canvas', timeout=5000)

    participant_page.fill('#wc-input', 'microservices')
    participant_page.click('#wc-go')

    # The word cloud word count is broadcast in the state message which the participant
    # receives and can render. Use a second participant page to observe the state:
    # simplest approach — check the word appears in the participant's #wc-my-words list.
    participant_page.wait_for_selector('#wc-my-words li', timeout=3000)
    items = participant_page.locator('#wc-my-words li').all_text_contents()
    assert 'microservices' in items, f"Expected 'microservices' in my-words list, got: {items}"


def test_close_wordcloud_returns_to_idle(server_url, participant_page):
    import requests
    requests.post(f"{server_url}/api/wordcloud/status", json={"active": True})

    participant_page.fill('#name-input', 'CloseTester')
    participant_page.click('#join-btn')
    participant_page.wait_for_selector('#wc-canvas', timeout=5000)

    requests.post(f"{server_url}/api/wordcloud/status", json={"active": False})

    # Participant returns to idle (no wc-canvas)
    participant_page.wait_for_selector('#wc-canvas', state='detached', timeout=5000)
```

Note: These tests use direct API calls for host actions to avoid needing Basic Auth setup in the browser. The test server (spawned in a subprocess) has no auth by default.

- [ ] **Step 2: Run E2E tests**

```bash
pytest test_e2e.py -v -k "wordcloud"
```
Expected: all pass.

- [ ] **Step 3: Run full test suite**

```bash
pytest test_main.py test_e2e.py -v
```
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add test_e2e.py
git commit -m "test: add E2E tests for word cloud flow"
```

---

## Task 8: Update C4 diagrams and CLAUDE.md backlog

**Files:**
- Modify: `adoc/c4_c3_components.puml` (if wordcloud router is a new component worth noting)
- Modify: `CLAUDE.md` (mark word cloud backlog item as done)

- [ ] **Step 1: Mark word cloud as complete in CLAUDE.md backlog**

In `CLAUDE.md`, find the backlog item:
```
- [ ] Implement word cloud feature (Phase 2)
```
Change to:
```
- [x] Implement word cloud feature (Phase 2)
```

- [ ] **Step 2: Update C4 C3 diagram if wordcloud router is relevant**

Open `adoc/c4_c3_components.puml`. If poll router is listed as a component, add wordcloud router similarly. Keep it minimal — just one line.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md adoc/
git commit -m "docs: mark word cloud complete, update C4 diagram"
```

---

## Verification Checklist

Before declaring done, run:

```bash
# Unit tests
pytest test_main.py -v

# E2E tests
pytest test_e2e.py -v

# Manual smoke (optional but recommended before deploy)
python3 -m uvicorn main:app --port 8000
# Open /host and / in browser, exercise the full flow
```

All tests must pass green.
