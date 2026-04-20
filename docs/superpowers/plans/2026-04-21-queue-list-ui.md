# Queue List UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Pop/Skip queue buttons with a persistent scrollable list of queued questions below the backstage textarea; host clicks any item to load it, then Send fires it and removes it from the queue.

**Architecture:** Simplify `PollQueue` to a plain list (no advance pointer), add `remove(index)` and expose all items via `GET /host/poll`; add `DELETE /queue/{index}` endpoint; update host HTML/JS to render the list, handle item selection, and wire Send/Clear buttons to the new interaction model.

**Tech Stack:** Python/FastAPI/Pydantic (daemon), vanilla JS + HTML (host UI), pytest + Starlette TestClient (tests)

---

## Files Changed

| File | Change |
|---|---|
| `daemon/quiz/queue.py` | Remove `_index`/`advance()`; update `current()` and `pending_count()`; add `remove(index)` |
| `daemon/quiz/queue_router.py` | Remove `/submit` and `/skip` routes; add `DELETE /{index}` |
| `daemon/poll/router.py` | Add `QueuedQuestion` model; update `PollQueueStatus`; update `get_poll_state()` |
| `tests/daemon/quiz/test_poll_queue.py` | New: unit tests for `PollQueue.remove()` |
| `tests/daemon/test_queue_router.py` | New: integration test for `DELETE /queue/{index}` |
| `static/host.html` | Remove Pop/Skip buttons; add Clear button; add `<ul id="queue-list">` |
| `static/host.js` | Remove old queue functions; add selection state; update `renderPollQueuePanel`, Send handler, Clear handler |

---

## Task 1: Simplify PollQueue — remove advance pointer, add remove()

**Files:**
- Modify: `daemon/quiz/queue.py`
- Create: `tests/daemon/quiz/test_poll_queue.py`

- [ ] **Step 1: Write failing tests**

Create `tests/daemon/quiz/test_poll_queue.py`:

```python
"""Unit tests for PollQueue."""
import pytest
from daemon.quiz.queue import PollQueue

Q1 = {"question": "Q1", "options": ["a", "b"], "correct_indices": [0]}
Q2 = {"question": "Q2", "options": ["c", "d"], "correct_indices": [1]}
Q3 = {"question": "Q3", "options": ["e", "f"], "correct_indices": [0]}


class TestPollQueueRemove:
    def test_remove_first_item_leaves_second_as_current(self):
        q = PollQueue()
        q.submit([Q1, Q2])
        q.remove(0)
        assert q.pending_count() == 1
        assert q.current()["question"] == "Q2"

    def test_remove_middle_item(self):
        q = PollQueue()
        q.submit([Q1, Q2, Q3])
        q.remove(1)
        assert q.pending_count() == 2
        assert q.all_items()[0]["question"] == "Q1"
        assert q.all_items()[1]["question"] == "Q3"

    def test_remove_last_item_leaves_empty(self):
        q = PollQueue()
        q.submit([Q1])
        q.remove(0)
        assert q.pending_count() == 0
        assert q.current() is None

    def test_remove_invalid_index_raises(self):
        q = PollQueue()
        q.submit([Q1])
        with pytest.raises(IndexError):
            q.remove(5)

    def test_current_returns_first_item(self):
        q = PollQueue()
        q.submit([Q1, Q2])
        assert q.current()["question"] == "Q1"

    def test_all_items_returns_full_list(self):
        q = PollQueue()
        q.submit([Q1, Q2, Q3])
        items = q.all_items()
        assert len(items) == 3
        assert items[1]["question"] == "Q2"

    def test_pending_count_equals_length(self):
        q = PollQueue()
        q.submit([Q1, Q2, Q3])
        assert q.pending_count() == 3
        q.remove(0)
        assert q.pending_count() == 2
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/victorrentea/workspace/training-assistant
uv run --extra dev --extra daemon pytest tests/daemon/quiz/test_poll_queue.py -v --confcutdir=tests/daemon 2>&1 | tail -20
```

Expected: `AttributeError: 'PollQueue' object has no attribute 'remove'` (or similar)

- [ ] **Step 3: Rewrite `daemon/quiz/queue.py`**

Replace the entire file:

```python
"""In-memory poll queue — stores pre-submitted questions for one-at-a-time firing."""


class PollQueue:
    def __init__(self):
        self._questions: list[dict] = []

    def submit(self, questions: list[dict]) -> None:
        """Replace the entire queue."""
        self._questions = list(questions)

    def current(self) -> dict | None:
        """Return the first question in the queue, or None if empty."""
        return self._questions[0] if self._questions else None

    def all_items(self) -> list[dict]:
        """Return all queued questions."""
        return list(self._questions)

    def pending_count(self) -> int:
        """Return the number of questions remaining."""
        return len(self._questions)

    def remove(self, index: int) -> None:
        """Remove the question at the given 0-based index."""
        del self._questions[index]

    def clear(self) -> None:
        """Discard all questions."""
        self._questions = []


quiz_queue = PollQueue()
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run --extra dev --extra daemon pytest tests/daemon/quiz/test_poll_queue.py -v --confcutdir=tests/daemon 2>&1 | tail -20
```

Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add daemon/quiz/queue.py tests/daemon/quiz/test_poll_queue.py
git commit -m "refactor(queue): simplify PollQueue — remove advance pointer, add remove(index) and all_items()"
```

---

## Task 2: Add QueuedQuestion model and update PollQueueStatus

**Files:**
- Modify: `daemon/poll/router.py` (lines 51–66 and 167–185)

- [ ] **Step 1: Add `QueuedQuestion` model and update `PollQueueStatus`**

In `daemon/poll/router.py`, replace the two classes at lines 51–53 and 55–66:

```python
# Replace this block:
class PollQueueStatus(BaseModel):
    pending: int
    current: dict | None = None
```

With:

```python
class QueuedQuestion(BaseModel):
    question: str
    options: list[str]
    correct_indices: list[int]


class PollQueueStatus(BaseModel):
    pending: int
    items: list[QueuedQuestion]
    current: QueuedQuestion | None = None  # always items[0] if non-empty
```

- [ ] **Step 2: Update `get_poll_state()` to populate `items`**

In `daemon/poll/router.py`, replace line 184:

```python
# Old:
queue=PollQueueStatus(pending=quiz_queue.pending_count(), current=quiz_queue.current()),
```

With:

```python
# New:
queue=PollQueueStatus(
    pending=quiz_queue.pending_count(),
    items=[QueuedQuestion(**q) for q in quiz_queue.all_items()],
    current=QueuedQuestion(**quiz_queue.current()) if quiz_queue.current() else None,
),
```

- [ ] **Step 3: Verify daemon starts cleanly**

```bash
cd /Users/victorrentea/workspace/training-assistant
uv run --extra dev --extra daemon python -c "from daemon.poll.router import host_router; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Run existing daemon tests**

```bash
uv run --extra dev --extra daemon pytest tests/daemon/ -v --confcutdir=tests/daemon -x -q 2>&1 | tail -20
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add daemon/poll/router.py
git commit -m "feat(queue): add QueuedQuestion model and items list to PollQueueStatus"
```

---

## Task 3: Add DELETE /queue/{index} endpoint; remove /submit and /skip

**Files:**
- Modify: `daemon/quiz/queue_router.py`
- Create: `tests/daemon/test_queue_router.py`

- [ ] **Step 1: Write failing test**

Create `tests/daemon/test_queue_router.py`:

```python
"""Integration tests for poll queue router."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from daemon.quiz.queue import PollQueue
from daemon.quiz.queue_router import router

Q1 = {"question": "Q1", "options": ["a", "b"], "correct_indices": [0]}
Q2 = {"question": "Q2", "options": ["c", "d"], "correct_indices": [1]}
Q3 = {"question": "Q3", "options": ["e", "f"], "correct_indices": [0]}


@pytest.fixture
def fresh_queue():
    return PollQueue()


@pytest.fixture
def client(fresh_queue):
    with patch("daemon.quiz.queue_router.quiz_queue", fresh_queue), \
         patch("daemon.quiz.queue_router.notify_host", AsyncMock()):
        app = FastAPI()
        app.include_router(router)
        yield TestClient(app), fresh_queue


class TestDeleteQueueItem:
    def test_delete_first_item_returns_204(self, client):
        tc, q = client
        q.submit([Q1, Q2])
        resp = tc.delete("/api/test-session/host/poll/queue/0")
        assert resp.status_code == 204

    def test_delete_removes_correct_item(self, client):
        tc, q = client
        q.submit([Q1, Q2, Q3])
        tc.delete("/api/test-session/host/poll/queue/1")
        assert q.pending_count() == 2
        assert q.all_items()[0]["question"] == "Q1"
        assert q.all_items()[1]["question"] == "Q3"

    def test_delete_out_of_range_returns_404(self, client):
        tc, q = client
        q.submit([Q1])
        resp = tc.delete("/api/test-session/host/poll/queue/5")
        assert resp.status_code == 404

    def test_delete_empty_queue_returns_404(self, client):
        tc, q = client
        resp = tc.delete("/api/test-session/host/poll/queue/0")
        assert resp.status_code == 404
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run --extra dev --extra daemon pytest tests/daemon/test_queue_router.py -v --confcutdir=tests/daemon 2>&1 | tail -20
```

Expected: `404 Not Found` because the route doesn't exist yet

- [ ] **Step 3: Update `daemon/quiz/queue_router.py`**

Replace the entire file:

```python
"""Poll queue router — host-only endpoints for pre-submitted poll questions."""
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from daemon import log as daemon_log
from daemon.quiz.queue import quiz_queue
from daemon.ws_messages import PollQueueUpdatedMsg
from daemon.ws_publish import notify_host

logger = logging.getLogger(__name__)

_LOG = "qz-queue"


# ── Pydantic models ──

class PollQueueQuestion(BaseModel):
    question: str
    options: list[str]
    correct_indices: list[int]


class SubmitQuestionsRequest(BaseModel):
    questions: list[PollQueueQuestion]


# ── Router ──

router = APIRouter(prefix="/api/{session_id}/host/poll/queue", tags=["poll"])


@router.post("", status_code=204)
async def submit_questions(body: SubmitQuestionsRequest):
    """Replace the entire poll queue with the submitted questions."""
    questions = [q.model_dump() for q in body.questions]
    quiz_queue.submit(questions)
    daemon_log.info(_LOG, f"Queue submitted: {len(questions)} question(s)")
    await notify_host(PollQueueUpdatedMsg())
    return Response(status_code=204)


@router.delete("/{index}", status_code=204)
async def remove_from_queue(index: int):
    """Remove the question at the given 0-based index from the queue."""
    try:
        removed = quiz_queue.all_items()[index]
        quiz_queue.remove(index)
    except IndexError:
        return JSONResponse({"error": f"No item at index {index}"}, status_code=404)
    await notify_host(PollQueueUpdatedMsg())
    daemon_log.info(_LOG, f"Removed queue item [{index}]: \"{removed['question'][:60]}\" — {quiz_queue.pending_count()} remaining")
    return Response(status_code=204)


@router.delete("", status_code=204)
async def clear_queue():
    """Clear the entire quiz queue."""
    quiz_queue.clear()
    await notify_host(PollQueueUpdatedMsg())
    daemon_log.info(_LOG, "Queue cleared")
    return Response(status_code=204)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run --extra dev --extra daemon pytest tests/daemon/test_queue_router.py -v --confcutdir=tests/daemon 2>&1 | tail -20
```

Expected: `4 passed`

- [ ] **Step 5: Run full daemon test suite**

```bash
uv run --extra dev --extra daemon pytest tests/daemon/ -v --confcutdir=tests/daemon -x -q 2>&1 | tail -20
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add daemon/quiz/queue_router.py tests/daemon/test_queue_router.py
git commit -m "feat(queue): add DELETE /queue/{index}; remove /submit and /skip endpoints"
```

---

## Task 4: Host HTML — remove Pop/Skip buttons, add Clear button and queue list

**Files:**
- Modify: `static/host.html` (lines 102–113)

- [ ] **Step 1: Replace the entire poll tab content block**

In `static/host.html`, find the `#tab-content-poll` div and its entire contents (lines 92–115) and replace:

```html
    <!-- Poll tab content -->
    <div id="tab-content-poll" class="tab-content">
      <!-- Backstage manual entry -->
      <div style="margin-top:.75rem;">
        <div style="display:flex; align-items:center; gap:.75rem; margin-bottom:.5rem;">
          <span style="font-size:.8rem; color:var(--muted); text-transform:uppercase; letter-spacing:.06em;">Backstage</span>
          <a href="#" onclick="event.preventDefault(); testOnePoll();" style="font-size:.8rem; color:var(--accent); text-decoration:none;">one</a>
          <a href="#" onclick="event.preventDefault(); pushDummyQueue();" style="font-size:.8rem; color:var(--accent); text-decoration:none;">queue</a>
        </div>
        <div id="poll-input" class="poll-composer" contenteditable="true" spellcheck="false"
             data-placeholder="Question title&#10;&#10;Option A&#10;Option B&#10;Option C"></div>
        <div style="display:flex; flex-direction:column; gap:.4rem; margin-top:.4rem;">
          <div class="btn-row" style="align-items:center;">
            <button class="btn" id="pop-queue-btn" onclick="popFromQueue()" disabled>⬆ Pop (0)</button>
            <button class="btn" id="backstage-skip-btn" onclick="pollQueueSkip()" disabled>⏭</button>
            <label style="display:flex; align-items:center; gap:.4rem; font-size:.9rem; color:var(--text); margin:0 0 0 .25rem;">
              <input type="text" inputmode="numeric" pattern="[0-9]*" id="correct-count" value="1" maxlength="1"
                     style="width:2.8rem; height:34px; box-sizing:border-box; text-align:center; background:var(--surface2); color:var(--text); border:1px solid var(--border); border-radius:6px; font-size:.9rem;" />
              correct
            </label>
            <button class="btn btn-success" id="create-btn" style="margin-left:auto;" disabled>▶</button>
          </div>
        </div>
      </div>
    </div>
```

With:

```html
    <!-- Poll tab content -->
    <div id="tab-content-poll" class="tab-content" style="overflow:hidden; display:flex; flex-direction:column;">
      <!-- Backstage manual entry -->
      <div style="margin-top:.75rem; flex-shrink:0;">
        <div style="display:flex; align-items:center; gap:.75rem; margin-bottom:.5rem;">
          <span style="font-size:.8rem; color:var(--muted); text-transform:uppercase; letter-spacing:.06em;">Backstage</span>
          <a href="#" onclick="event.preventDefault(); testOnePoll();" style="font-size:.8rem; color:var(--accent); text-decoration:none;">one</a>
          <a href="#" onclick="event.preventDefault(); pushDummyQueue();" style="font-size:.8rem; color:var(--accent); text-decoration:none;">queue</a>
        </div>
        <div id="poll-input" class="poll-composer" contenteditable="true" spellcheck="false"
             data-placeholder="Question title&#10;&#10;Option A&#10;Option B&#10;Option C"></div>
        <div style="display:flex; flex-direction:column; gap:.4rem; margin-top:.4rem;">
          <div class="btn-row" style="align-items:center;">
            <button class="btn" id="clear-queue-item-btn" onclick="clearBackstage()">✕ Clear</button>
            <label style="display:flex; align-items:center; gap:.4rem; font-size:.9rem; color:var(--text); margin:0 0 0 .25rem;">
              <input type="text" inputmode="numeric" pattern="[0-9]*" id="correct-count" value="1" maxlength="1"
                     style="width:2.8rem; height:34px; box-sizing:border-box; text-align:center; background:var(--surface2); color:var(--text); border:1px solid var(--border); border-radius:6px; font-size:.9rem;" />
              correct
            </label>
            <button class="btn btn-success" id="create-btn" style="margin-left:auto;" disabled>▶</button>
          </div>
        </div>
      </div>
      <ul id="queue-list" style="flex:1; min-height:0; overflow-y:auto; margin:.5rem 0 0 0; padding:.25rem 0 0 1.5rem; list-style:disc;"></ul>
    </div>
```

- [ ] **Step 2: Verify HTML is valid — open host page locally**

```bash
open http://localhost:8081/
```

Confirm the left panel loads without JS errors; the queue list area is visible below the button row (initially empty).

---

## Task 5: Host JS — queue selection state, renderPollQueuePanel, click handler

**Files:**
- Modify: `static/host.js`

- [ ] **Step 1: Add selection state variables**

Near line 1527, after `const pollInput = document.getElementById('poll-input');`, add:

```javascript
  let selectedQueueIndex = null;   // index of queue item currently loaded into textarea
  let selectedQueueItem = null;    // full {question, options, correct_indices} of selected item
```

- [ ] **Step 2: Replace `renderPollQueuePanel` (currently a no-op at line ~1955)**

Find and replace:

```javascript
  function renderPollQueuePanel(_data) {
    // Queue panel removed from UI; Pop button state handled by updatePopButton
  }
```

With:

```javascript
  function renderPollQueuePanel(queue) {
    const list = document.getElementById('queue-list');
    if (!list) return;
    const items = queue?.items || [];
    list.innerHTML = items.map((item, i) =>
      `<li data-idx="${i}" style="cursor:pointer; padding:.2rem .25rem; border-radius:4px; ${i === selectedQueueIndex ? 'background:var(--surface2);' : ''}">${escHtml(item.question)}</li>`
    ).join('');
    list.querySelectorAll('li').forEach(li => {
      li.addEventListener('click', () => selectQueueItem(parseInt(li.dataset.idx), items));
    });
  }

  function escHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function selectQueueItem(index, items) {
    const item = items[index];
    if (!item) return;
    selectedQueueIndex = index;
    selectedQueueItem = item;
    const text = item.question + '\n\n' + item.options.join('\n');
    initComposer(text);
    const cc = document.getElementById('correct-count');
    if (cc) { cc.value = item.correct_indices.length || 1; cc.readOnly = true; }
    // Re-render list to update highlight
    const list = document.getElementById('queue-list');
    if (list) list.querySelectorAll('li').forEach((li, i) => {
      li.style.background = i === index ? 'var(--surface2)' : '';
    });
    pollInput.focus();
  }
```

- [ ] **Step 3: Remove obsolete queue functions from `static/host.js`**

Delete the following functions entirely:
- `function updatePopButton(queue) { ... }` (lines ~1900–1906)
- `async function popFromQueue() { ... }` (lines ~1908–1926)
- `async function pollQueueFire() { ... }` (lines ~1959–1976)
- `async function pollQueueSkip() { ... }` (lines ~1978–1995)

Also remove the `updatePopButton(data.queue)` call in `fetchPollState()` (line ~1741).

- [ ] **Step 4: Update the poll input listener to remove disabled-re-enable logic**

Find (line ~1614):

```javascript
  pollInput.addEventListener('input', () => {
    reclassifyLines();
    const cc = document.getElementById('correct-count');
    if (cc && cc.disabled) cc.disabled = false;
  });
```

Replace with:

```javascript
  pollInput.addEventListener('input', () => {
    reclassifyLines();
  });
```

- [ ] **Step 5: Verify page loads without JS errors**

```bash
open http://localhost:8081/
```

Check browser console for errors. The queue list should render when items are present (use `pushDummyQueue()` from the "queue" debug link).

- [ ] **Step 6: Commit**

```bash
git add static/host.js
git commit -m "feat(host-js): add queue list rendering and item selection"
```

---

## Task 6: Host JS — Send button queue-mode logic + Clear button

**Files:**
- Modify: `static/host.js`

- [ ] **Step 1: Update the create-btn click handler**

Find the create-btn event listener (line ~1636). Replace it:

```javascript
  // Old handler:
  document.getElementById('create-btn').addEventListener('click', async () => {
    const { question, options } = parsePollInput();

    if (!question) { toast('Enter a question'); return; }
    if (options.length < 2) { toast('Add at least 2 options'); return; }

    const correctCountEl = document.getElementById('correct-count');
    const correct_count_val = parseInt(correctCountEl.value) || 1;
    const multi = correct_count_val > 1;
    const correct_count = multi ? correct_count_val : null;
    const res = await fetch(API('/poll/manual/submit'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, options, multi, correct_count }),
    });
    if (res.ok) {
      // Erase stale correct-opts and LLM hints for this question
      localStorage.removeItem('host_correct_' + question);
      localStorage.removeItem('host_llm_hints_' + question);
      correctOptIds = new Set();
      toast('Poll created & opened ✓');
      pollInput.innerHTML = '<div><br></div>';
      reclassifyLines();
      const cc = document.getElementById('correct-count');
      cc.value = 1; cc.disabled = false;
    } else {
      const data = await res.json().catch(() => ({}));
      toast(data.detail || data.error || 'Error');
    }
  });
```

With:

```javascript
  document.getElementById('create-btn').addEventListener('click', async () => {
    const { question, options } = parsePollInput();

    if (!question) { toast('Enter a question'); return; }
    if (options.length < 2) { toast('Add at least 2 options'); return; }

    const correctCountEl = document.getElementById('correct-count');
    const correct_count_val = parseInt(correctCountEl.value) || 1;
    const multi = correct_count_val > 1;
    const correct_count = multi ? correct_count_val : null;
    const res = await fetch(API('/poll/manual/submit'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, options, multi, correct_count }),
    });
    if (res.ok) {
      localStorage.removeItem('host_correct_' + question);
      localStorage.removeItem('host_llm_hints_' + question);
      correctOptIds = new Set();
      toast('Poll created & opened ✓');
      // If a queue item was selected, remove it from the queue
      if (selectedQueueIndex !== null) {
        await fetch(API(`/poll/queue/${selectedQueueIndex}`), { method: 'DELETE' });
        selectedQueueIndex = null;
        selectedQueueItem = null;
      }
      _resetBackstage();
    } else {
      const data = await res.json().catch(() => ({}));
      toast(data.detail || data.error || 'Error');
    }
  });

  function _resetBackstage() {
    pollInput.innerHTML = '<div><br></div>';
    reclassifyLines();
    const cc = document.getElementById('correct-count');
    if (cc) { cc.value = 1; cc.readOnly = false; }
  }
```

- [ ] **Step 2: Add `clearBackstage` function (for the Clear button)**

Add after `_resetBackstage`:

```javascript
  window.clearBackstage = function() {
    selectedQueueIndex = null;
    selectedQueueItem = null;
    _resetBackstage();
    // Re-render list to remove highlight
    const list = document.getElementById('queue-list');
    if (list) list.querySelectorAll('li').forEach(li => { li.style.background = ''; });
  };
```

- [ ] **Step 3: Manual smoke test — queue flow**

1. Open `http://localhost:8081/` in browser
2. Click "queue" debug link — queues 2 dummy questions
3. Confirm two items appear in the bullet list below the button row
4. Click the first item — confirm textarea fills with question+options, correct-count shows value as readonly
5. Click Send (▶) — confirm poll opens, item disappears from list, textarea clears, correct-count becomes editable
6. Click second item in list — confirm textarea fills
7. Click Clear (✕) — confirm textarea clears, correct-count editable, no highlight

- [ ] **Step 4: Commit**

```bash
git add static/host.js
git commit -m "feat(host-js): wire Send to remove queue item; add Clear button handler"
```

---

## Task 7: Push and verify production deploy

- [ ] **Step 1: Run full test suite**

```bash
uv run --extra dev --extra daemon bash tests/check-all.sh 2>&1 | tail -30
```

Expected: all pass

- [ ] **Step 2: Push to master**

```bash
git fetch origin && git rebase origin/master && git push origin master
```

- [ ] **Step 3: Wait for Railway deploy**

Monitor `$WORKSHOP_SERVER_URL` — Railway deploys in ~40-50s after push.

- [ ] **Step 4: Smoke test on production**

1. Open `$WORKSHOP_SERVER_URL` host page
2. Click "queue" link → two items appear in list
3. Click an item → loads into textarea, correct-count readonly
4. Send → poll opens, item removed from list
5. Confirm Clear button resets state correctly
