# Gamify Q&A Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Encourage participant engagement during Q&A by awarding points to upvoters (not just authors) and showing rotating toast notifications every 15s (or immediately when the list is empty).

**Architecture:** Two independent changes: (1) backend awards +25 pts to the upvoter in `routers/qa.py`; (2) frontend adds a non-blocking toast rotation system in `static/participant.js` that activates while Q&A is the current activity.

**Tech Stack:** Python/FastAPI (backend), Vanilla JS (frontend), pytest + FastAPI TestClient (tests)

---

## File Map

| File | Change |
|---|---|
| `routers/qa.py` | Award +25 pts to upvoter on upvote |
| `test_main.py` | Add test: upvoter earns points; update existing point-total assertion |
| `static/participant.js` | Add toast component + rotation logic (Q&A activity only) |
| `static/participant.css` | Add toast styles (fade-in/out) |

---

### Task 1: Award points to upvoter (backend)

**Files:**
- Modify: `routers/qa.py:60-76`
- Modify: `test_main.py` (existing Q&A upvote tests)

- [ ] **Step 1: Update the existing test to expect upvoter also earns points**

Find `test_upvote_question_awards_points_to_author` in `test_main.py` and extend it to also assert Bob (the upvoter) earns +25 pts. Use the existing `self._submit` helper (defined at line 721):

```python
def test_upvote_question_awards_points_to_author(self, session):
    qid = self._submit(session._client, "Alice", "What is DDD?")
    resp = session._client.post("/api/qa/upvote", json={"name": "Bob", "question_id": qid})
    assert resp.status_code == 200
    # Alice gets 100 (submit) + 50 (upvote) = 150
    assert state.scores.get("Alice") == 150
    # Bob gets 25 for upvoting
    assert state.scores.get("Bob") == 25
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/victorrentea/PycharmProjects/training-assistant
python -m pytest test_main.py::TestQA::test_upvote_question_awards_points_to_author -v
```
Expected: FAIL — `assert state.scores.get("Bob") == 25` fails (Bob currently gets 0)

- [ ] **Step 3: Award +25 pts to upvoter in `routers/qa.py`**

In `upvote_question()`, after awarding to author, add:
```python
    # Award +25 points to the upvoter
    state.scores[name] = state.scores.get(name, 0) + 25
```

Full updated block (lines 71-75):
```python
    q["upvoters"].add(name)
    # Award +50 points to the question author
    author = q["author"]
    state.scores[author] = state.scores.get(author, 0) + 50
    # Award +25 points to the upvoter
    state.scores[name] = state.scores.get(name, 0) + 25
    await broadcast(build_state_message())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest test_main.py::TestQA -v
```
Expected: All Q&A tests PASS

- [ ] **Step 5: Commit**

```bash
git add routers/qa.py test_main.py
git commit -m "feat: award +25 pts to upvoter in Q&A (not just the author)"
```

---

### Task 2: Rotating toast notifications in participant Q&A view (frontend)

**Files:**
- Modify: `static/participant.js` (add toast state + functions, hook into Q&A render and activity changes)
- Modify: `static/participant.css` (add `.qa-toast` styles)

#### Toast design

- A fixed-position `div#qa-toast` is injected once into the DOM (outside `#content`), hidden by default.
- When Q&A becomes active: start a 15s interval that shows the next message. Also show immediately if question list is empty.
- When Q&A becomes inactive (activity changes): clear the interval and hide the toast.
- Each toast: fade in (0.4s), stay visible ~4s, fade out (0.4s).
- 5 rotating messages (no point numbers):
  1. "💬 Ask a question — earn points!"
  2. "👍 Upvote a great question — both you and the author earn points!"
  3. "🏆 The more you engage, the higher you rank!"
  4. "🤔 Got a burning question? Type it in!"
  5. "⬆️ See a question you like? Give it an upvote!"

- [ ] **Step 1: Add toast CSS to `static/participant.css`**

```css
/* Q&A engagement toast */
#qa-toast {
  position: fixed;
  bottom: 70px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(30, 30, 50, 0.92);
  color: var(--text);
  border: 1px solid var(--accent2);
  border-radius: 10px;
  padding: 10px 20px;
  font-size: 0.9rem;
  max-width: 340px;
  text-align: center;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.4s ease;
  z-index: 1000;
}
#qa-toast.visible {
  opacity: 1;
}
```

- [ ] **Step 2: Add toast HTML element to `static/participant.html`**

Find the `<body>` tag in `participant.html` and insert the toast div just before `</body>`:

```html
<div id="qa-toast"></div>
```

- [ ] **Step 3: Add toast JS to `static/participant.js`**

Add these variables near the top of the script (alongside other `let` declarations):

```javascript
const _QA_TOASTS = [
  "💬 Ask a question — earn points!",
  "👍 Upvote a great question — both you and the author earn points!",
  "🏆 The more you engage, the higher you rank!",
  "🤔 Got a burning question? Type it in!",
  "⬆️ See a question you like? Give it an upvote!",
];
let _qaToastIndex = 0;
let _qaToastInterval = null;
let _qaToastTimeout = null;
```

Add these functions (near the Q&A section, around line 523):

```javascript
function _showQAToast() {
  const el = document.getElementById('qa-toast');
  if (!el) return;
  el.textContent = _QA_TOASTS[_qaToastIndex % _QA_TOASTS.length];
  _qaToastIndex++;
  el.classList.add('visible');
  clearTimeout(_qaToastTimeout);
  _qaToastTimeout = setTimeout(() => el.classList.remove('visible'), 4400);
}

function _startQAToasts(questions) {
  _stopQAToasts();
  // Show immediately if no questions yet
  if (!questions || questions.length === 0) _showQAToast();
  _qaToastInterval = setInterval(_showQAToast, 15000);
}

function _stopQAToasts() {
  clearInterval(_qaToastInterval);
  clearTimeout(_qaToastTimeout);
  _qaToastInterval = null;
  const el = document.getElementById('qa-toast');
  if (el) el.classList.remove('visible');
}
```

- [ ] **Step 4: Hook `_startQAToasts` into Q&A screen activation**

In `renderQAScreen()` (line 524), the function has two branches:
- Line 527: early return branch — "already on Q&A screen, just refresh list" — do NOT add call here
- Line 547: `updateQAList(questions, myName)` — this is the fresh-build branch

Add `_startQAToasts(questions)` immediately **after** the `updateQAList(questions, myName)` call on line 547 (end of fresh-build branch), **not** inside `updateQAList` itself:

```javascript
    updateQAList(questions, myName);
    _startQAToasts(questions);  // ← add this line
  }  // end of renderQAScreen
```

- [ ] **Step 5: Hook `_stopQAToasts` into `renderQACleanup` and `leave`**

`renderQACleanup()` at line 611 is called whenever the activity switches away from Q&A (line 238 in the ws handler). Add the stop call there:

```javascript
  function renderQACleanup() {
    _stopQAToasts();  // ← add this line
    // Q&A DOM is inside #content which gets replaced when switching activities
  }
```

Also add `_stopQAToasts()` inside the `leave()` function (around line 110) to prevent a zombie interval if the participant leaves while Q&A is active:

```javascript
  function leave() {
    _stopQAToasts();  // ← add at top of leave()
    // ... existing leave logic
  }
```

- [ ] **Step 6: Manual smoke test**

1. Start server: `python3 -m uvicorn main:app --reload --port 8000`
2. Open participant page, join with any name
3. Host activates Q&A (via host panel)
4. Verify: toast appears immediately (list is empty)
5. Wait 15s — verify next toast appears
6. Submit a question — toast cycle continues
7. Host switches to Poll activity — verify toast disappears
8. Host switches back to Q&A — verify toasts resume

- [ ] **Step 7: Commit**

```bash
git add static/participant.js static/participant.css static/participant.html
git commit -m "feat: rotating Q&A engagement toasts every 15s; show immediately when list is empty"
```

---

### Task 3: Push and deploy

- [ ] **Step 1: Push to master**

```bash
git push
```

- [ ] **Step 2: Start deploy monitor**

```bash
bash wait-for-deploy.sh &
```

- [ ] **Step 3: Update backlog**

In `backlog.md`, mark the gamify Q&A item as `[x]`.

```bash
git add backlog.md
git commit -m "chore: mark gamify Q&A item done"
git push
```
