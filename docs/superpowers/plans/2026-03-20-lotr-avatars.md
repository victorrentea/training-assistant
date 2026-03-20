# LOTR Avatars Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add LOTR-themed chibi avatars to participants, displayed everywhere names appear.

**Architecture:** Avatar assignment logic in `state.py`, broadcast via `messaging.py`, rendered in both participant and host frontends. Avatar images are static PNGs in `static/avatars/`. Assignment is deterministic and once-per-UUID.

**Tech Stack:** Python/FastAPI backend, vanilla JS frontend, static PNG assets.

**Spec:** `docs/superpowers/specs/2026-03-20-lotr-avatars-design.md`

---

### Task 1: Backend — Avatar Assignment Logic

**Files:**
- Modify: `state.py` (add `participant_avatars` to `reset()`, add `get_avatar_filename()` and `assign_avatar()`)
- Test: `test_main.py`

- [ ] **Step 1: Write failing tests for avatar assignment**

Add a new test class to `test_main.py`:

```python
class TestAvatarAssignment:

    def test_lotr_name_gets_matching_avatar(self):
        from state import AppState, assign_avatar, get_avatar_filename
        s = AppState()
        avatar = assign_avatar(s, "test-uuid-1", "Gandalf")
        assert avatar == "gandalf.png"
        assert s.participant_avatars["test-uuid-1"] == "gandalf.png"

    def test_custom_name_gets_deterministic_avatar(self):
        from state import AppState, assign_avatar
        s = AppState()
        a1 = assign_avatar(s, "550e8400-e29b-41d4-a716-446655440000", "Bob")
        a2 = assign_avatar(s, "550e8400-e29b-41d4-a716-446655440000", "Bob")
        assert a1 == a2  # same UUID → same avatar
        assert a1.endswith(".png")

    def test_assign_once_rename_keeps_avatar(self):
        from state import AppState, assign_avatar
        s = AppState()
        a1 = assign_avatar(s, "test-uuid-1", "Gandalf")
        a2 = assign_avatar(s, "test-uuid-1", "Bob")  # rename
        assert a1 == a2 == "gandalf.png"  # avatar unchanged

    def test_get_avatar_filename_slugs(self):
        from state import get_avatar_filename
        assert get_avatar_filename("Gandalf") == "gandalf.png"
        assert get_avatar_filename("Tom Bombadil") == "tom-bombadil.png"
        assert get_avatar_filename("The One Ring") == "the-one-ring.png"
        assert get_avatar_filename("Grima Wormtongue") == "grima-wormtongue.png"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest test_main.py::TestAvatarAssignment -v`
Expected: FAIL — `assign_avatar` and `get_avatar_filename` not importable

- [ ] **Step 3: Implement avatar logic in state.py**

Add `participant_avatars: dict[str, str] = {}` to `AppState.reset()` after `self.participant_names`.

Add two module-level functions after the `AppState` class:

```python
def get_avatar_filename(name: str) -> str:
    """Convert a LOTR name to its avatar filename slug."""
    return name.lower().replace(' ', '-') + '.png'


def assign_avatar(app_state: AppState, uuid: str, name: str) -> str:
    """Assign avatar to UUID. Returns existing avatar if already assigned (assign-once)."""
    if uuid in app_state.participant_avatars:
        return app_state.participant_avatars[uuid]
    if name in LOTR_NAMES:
        avatar = get_avatar_filename(name)
    else:
        index = int(uuid.replace('-', ''), 16) % len(LOTR_NAMES)
        avatar = get_avatar_filename(LOTR_NAMES[index])
    app_state.participant_avatars[uuid] = avatar
    return avatar
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest test_main.py::TestAvatarAssignment -v`
Expected: all 4 PASS

- [ ] **Step 5: Commit**

```bash
git add state.py test_main.py
git commit -m "feat: avatar assignment logic with assign-once rule"
```

---

### Task 2: Backend — Wire Avatar Into WebSocket and Messaging

**Files:**
- Modify: `routers/ws.py` (call `assign_avatar` in both set_name paths: initial at line 68 and rename at line 79)
- Modify: `messaging.py` (add avatar fields to `build_participant_state`, `build_host_state`, `broadcast_participant_update`, `_build_qa_for_participant`, `_build_qa_for_host`)
- Test: `test_main.py`

- [ ] **Step 1: Write failing tests for avatar in state messages**

Add to `TestAvatarAssignment` class in `test_main.py`:

```python
    def test_avatar_in_participant_state_on_connect(self, session):
        """Participant state includes my_avatar after set_name."""
        with session.participant("Legolas") as p:
            assert p._last_state.get("my_avatar") == "legolas.png"

    def test_avatar_in_qa_question(self, session):
        """Q&A questions include author_avatar."""
        session._client.post("/api/activity", json={"activity": "qa"},
                             headers=_HOST_AUTH_HEADERS)
        with session.participant("Gimli") as p:
            p.send({"type": "qa_submit", "text": "Test question?"})
            msg = p._recv("state")
            questions = msg.get("qa_questions", [])
            assert len(questions) == 1
            assert questions[0].get("author_avatar") == "gimli.png"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest test_main.py::TestAvatarAssignment::test_avatar_in_participant_state_on_connect test_main.py::TestAvatarAssignment::test_avatar_in_qa_question -v`
Expected: FAIL — `my_avatar` not in state message

- [ ] **Step 3: Modify routers/ws.py — call assign_avatar on BOTH set_name paths**

Import `assign_avatar` and call it in both places:

```python
from state import state, ActivityType, assign_avatar
```

In the **initial** set_name block (line 68, before `named = True`):
```python
                state.participant_names[pid] = name
                assign_avatar(state, pid, name)
                named = True
```

In the **rename** set_name block (line 79, after setting name):
```python
                if name:
                    state.participant_names[pid] = name
                    assign_avatar(state, pid, name)  # no-op if already assigned
                    await broadcast_participant_update()
```

- [ ] **Step 4: Modify messaging.py — add avatar fields to all message builders**

In `build_participant_state()` (line 67), add after `my_score`:
```python
        "my_avatar": state.participant_avatars.get(pid, ""),
```

In `build_host_state()` (line 87-92), add `avatar` to participant entries:
```python
        participants_list.append({
            "uuid": pid,
            "name": name,
            "score": score,
            "location": loc,
            "avatar": state.participant_avatars.get(pid, ""),
        })
```

In `broadcast_participant_update()` (line 155-160), add `avatar` to participant entries:
```python
        participants_list.append({
            "uuid": pid,
            "name": name,
            "score": state.scores.get(pid, 0),
            "location": state.locations.get(pid, ""),
            "avatar": state.participant_avatars.get(pid, ""),
        })
```

In `_build_qa_for_participant()` (line 22-32), add to the question dict:
```python
            "author_avatar": state.participant_avatars.get(q["author"], ""),
```

In `_build_qa_for_host()` (line 41-49), add to the question dict:
```python
            "author_avatar": state.participant_avatars.get(q["author"], ""),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest test_main.py::TestAvatarAssignment -v`
Expected: all PASS

- [ ] **Step 6: Run ALL existing tests for regressions**

Run: `python3 -m pytest test_main.py -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add routers/ws.py messaging.py test_main.py
git commit -m "feat: wire avatar into WebSocket state and messaging"
```

---

### Task 3: Generate Avatar Images

**Files:**
- Create: `static/avatars/` directory with 30 PNG files

- [ ] **Step 1: Create the avatars directory**

```bash
mkdir -p static/avatars
```

- [ ] **Step 2: Generate 30 LOTR chibi avatar images (64x64px PNG)**

Use an AI image generation tool to create chibi/cartoon-style portraits for each LOTR name. Required filenames (must match exactly):

```
frodo.png, samwise.png, gandalf.png, aragorn.png, legolas.png, gimli.png, boromir.png,
merry.png, pippin.png, galadriel.png, elrond.png, saruman.png, faramir.png,
eowyn.png, theoden.png, treebeard.png, bilbo.png, thorin.png, smaug.png, gollum.png,
radagast.png, tom-bombadil.png, glorfindel.png, celeborn.png, arwen.png, eomer.png,
haldir.png, shadowfax.png, grima-wormtongue.png, the-one-ring.png
```

Style: consistent chibi/cartoon, bright colors, recognizable characters. Non-humanoid entries (Shadowfax=horse, The One Ring=ring, Smaug=dragon, Treebeard=ent) as stylized illustrations.

If AI generation is not available, create simple colored-circle placeholder PNGs with the first letter of each name. These can be replaced later with proper art.

- [ ] **Step 3: Verify all 30 files exist**

```bash
ls static/avatars/*.png | wc -l  # must be 30
```

- [ ] **Step 4: Commit**

```bash
git add static/avatars/
git commit -m "feat: add 30 LOTR chibi avatar images"
```

---

### Task 4: Frontend — Participant Avatar Display

**Files:**
- Modify: `static/common.css` (add `.avatar` and `.avatar-fallback` classes)
- Modify: `static/participant.html` (add avatar `<img>` in top bar between mic and name)
- Modify: `static/participant.js` (read `my_avatar` from state, render avatar in top bar and Q&A)

- [ ] **Step 1: Add `.avatar` CSS classes to common.css**

Append to `static/common.css`:

```css
.avatar {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    object-fit: cover;
    vertical-align: middle;
    flex-shrink: 0;
}
.avatar-fallback {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-weight: bold;
    font-size: 14px;
    color: var(--text);
    flex-shrink: 0;
}
```

- [ ] **Step 2: Add avatar img to participant top bar HTML**

In `static/participant.html`, between the `<span class="mic-icon">🎙</span>` and the `<span><span class="dot">` block, insert:

```html
<img id="my-avatar" class="avatar" style="display:none" alt="">
```

- [ ] **Step 3: Update participant.js to display avatar in top bar**

In the state message handler, after processing `my_score`, add:

```javascript
if (msg.my_avatar) {
    const avatarEl = document.getElementById('my-avatar');
    avatarEl.src = '/static/avatars/' + msg.my_avatar;
    avatarEl.style.display = '';
    avatarEl.onerror = function() {
        // Fallback: replace with colored circle + initial
        const fallback = document.createElement('span');
        fallback.className = 'avatar-fallback';
        fallback.textContent = (window._myName || '?')[0].toUpperCase();
        fallback.style.background = avatarColorFromUuid(window._myUuid);
        this.replaceWith(fallback);
    };
}
```

Add a helper function for deterministic fallback color:

```javascript
function avatarColorFromUuid(uuid) {
    const hash = parseInt((uuid || '').replace(/-/g, '').slice(0, 8), 16);
    const hue = hash % 360;
    return `hsl(${hue}, 60%, 40%)`;
}
```

- [ ] **Step 4: Update participant.js Q&A rendering to include avatars**

In the Q&A question rendering function (around line 688-706), add avatar before the author name:

```javascript
const avatarHtml = q.author_avatar
    ? `<img src="/static/avatars/${escHtml(q.author_avatar)}" class="avatar" style="width:24px;height:24px" onerror="this.style.display='none'">`
    : '';
```

Insert `avatarHtml` before the `<span class="qa-author-p">` in the template.

- [ ] **Step 5: Verify in browser**

Start server: `python3 -m uvicorn main:app --reload --port 8000`
Open http://localhost:8000/ — verify avatar appears in top bar between mic icon and name.
Submit a Q&A question — verify avatar appears next to author name.

- [ ] **Step 6: Take screenshot for proof**

- [ ] **Step 7: Commit**

```bash
git add static/common.css static/participant.html static/participant.js
git commit -m "feat: display avatar in participant UI (top bar + Q&A)"
```

---

### Task 5: Frontend — Host Avatar Display

**Files:**
- Modify: `static/host.js` (add avatar to participant list rendering and Q&A rendering)
- Modify: `static/host.css` (alignment tweaks for avatars in participant list)

- [ ] **Step 1: Update host.js to store and display participant avatars**

Add a `participantAvatars` map (keyed by name) and populate it from participant update messages. In the message handler where `msg.participants` is received:

```javascript
if (msg.participants) {
    msg.participants.forEach(p => { participantAvatars[p.name] = p.avatar; });
}
```

In `renderParticipantList()` (around line 236-268), add avatar before each name:

```javascript
const avatar = participantAvatars[n];
const avatarHtml = avatar
    ? `<img src="/static/avatars/${escHtml(avatar)}" class="avatar" style="width:28px;height:28px" onerror="this.style.display='none'">`
    : '';
return `<li>${avatarHtml}${escHtml(n)}${scoreTag}${locLabel ? ... : ''}</li>`;
```

- [ ] **Step 2: Update host.js Q&A rendering to include avatars**

In `renderQAList()` (around line 1031-1064), add avatar before the author span:

```javascript
const avatarHtml = q.author_avatar
    ? `<img src="/static/avatars/${escHtml(q.author_avatar)}" class="avatar" style="width:24px;height:24px" onerror="this.style.display='none'">`
    : '';
```

Insert before `<span class="qa-author">`.

- [ ] **Step 3: Add host CSS tweaks for avatar alignment**

In `static/host.css`, ensure participant list items align properly with avatars:

```css
.pax-list li {
    display: flex;
    align-items: center;
    gap: 8px;
}
```

- [ ] **Step 4: Verify host panel in browser**

Open http://localhost:8000/host — verify avatars appear in participant list and Q&A section.

- [ ] **Step 5: Take screenshot for proof**

- [ ] **Step 6: Commit**

```bash
git add static/host.js static/host.css
git commit -m "feat: display avatar in host UI (participant list + Q&A)"
```

---

### Task 6: Update Documentation and Final Verification

**Files:**
- Modify: `CLAUDE.md` (add `participant_avatars` to AppState model)
- Modify: `backlog.md` (mark issues #12 and #13 done)

- [ ] **Step 1: Update CLAUDE.md AppState model**

Add `participant_avatars: dict[str, str]` to the AppState model documentation, with comment `# uuid → avatar filename`.

- [ ] **Step 2: Update backlog.md**

Mark issues #12 and #13 as done.

- [ ] **Step 3: Run all tests**

```bash
python3 -m pytest test_main.py -v
```

Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md backlog.md
git commit -m "docs: update AppState model and backlog for avatars"
```
