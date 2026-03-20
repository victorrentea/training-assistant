# Session Notes Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Inject session notes (trainer's written agenda) as a high-weight primary source into every quiz generation prompt, and show the notes detection status on the Agent badge in the host UI.

**Architecture:** `find_session_folder()` scans `SESSIONS_FOLDER` for a date-range folder matching today, reads the most recent `.txt` file inside it, and stores both paths in `Config`. `auto_generate` and `auto_generate_topic` in `quiz_core.py` call a new `read_session_notes()` helper and prepend notes to the prompt. The daemon detects the folder on startup and re-detects on date change. `POST /api/quiz-status` is extended to carry `session_folder`/`session_notes` names; `AppState` stores them; `build_state_message()` broadcasts them; `host.js` updates the Agent badge color/tooltip.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, vanilla JS.

---

## File Map

| File | Change |
|---|---|
| `quiz_core.py` | Add `session_folder`/`session_notes` to `Config`; add `find_session_folder()` and `read_session_notes()`; update `auto_generate` and `auto_generate_topic` |
| `quiz_daemon.py` | Call `find_session_folder()` at startup; re-detect on date change; extend `POST /api/quiz-status` payload |
| `state.py` | Add `daemon_session_folder: Optional[str]` and `daemon_session_notes: Optional[str]` |
| `routers/quiz.py` | Extend `QuizStatus` model and `update_quiz_status` handler |
| `messaging.py` | Include new fields in `build_state_message()` |
| `static/host.js` | Update `renderDaemonStatus` call and implementation |
| `test_quiz_core.py` | New test file for `find_session_folder()` |

---

### Task 1: Add Config fields and `find_session_folder()`

**Files:**
- Modify: `quiz_core.py` (Config dataclass, imports, new function)
- Create: `test_quiz_core.py`

- [ ] **Step 1: Write failing tests for `find_session_folder()`**

```python
# test_quiz_core.py
import pytest
from datetime import date
from pathlib import Path
import tempfile, os

from quiz_core import find_session_folder


def _make_folder(base: Path, name: str) -> Path:
    p = base / name
    p.mkdir()
    return p


def test_finds_single_day_folder(tmp_path):
    folder = _make_folder(tmp_path, "2026-03-19 CleanCode@acme")
    notes = folder / "notes.txt"
    notes.write_text("agenda")
    os.environ["SESSIONS_FOLDER"] = str(tmp_path)
    sf, sn = find_session_folder(date(2026, 3, 19))
    assert sf == folder
    assert sn == notes


def test_no_match_outside_range(tmp_path):
    _make_folder(tmp_path, "2026-03-19 Workshop")
    os.environ["SESSIONS_FOLDER"] = str(tmp_path)
    sf, sn = find_session_folder(date(2026, 3, 20))
    assert sf is None and sn is None


def test_multi_day_range_dd(tmp_path):
    folder = _make_folder(tmp_path, "2026-03-18..21 Workshop")
    (folder / "notes.txt").write_text("x")
    os.environ["SESSIONS_FOLDER"] = str(tmp_path)
    sf, sn = find_session_folder(date(2026, 3, 20))
    assert sf == folder


def test_multi_day_range_mm_dd(tmp_path):
    folder = _make_folder(tmp_path, "2026-03-30..04-02 Workshop")
    (folder / "notes.txt").write_text("x")
    os.environ["SESSIONS_FOLDER"] = str(tmp_path)
    sf, sn = find_session_folder(date(2026, 4, 1))
    assert sf == folder


def test_no_notes_file(tmp_path):
    folder = _make_folder(tmp_path, "2026-03-19 Workshop")
    os.environ["SESSIONS_FOLDER"] = str(tmp_path)
    sf, sn = find_session_folder(date(2026, 3, 19))
    assert sf == folder
    assert sn is None


def test_missing_sessions_folder():
    os.environ["SESSIONS_FOLDER"] = "/nonexistent/path/xyz"
    sf, sn = find_session_folder(date(2026, 3, 19))
    assert sf is None and sn is None


def test_multiple_matches_uses_latest_start(tmp_path):
    f1 = _make_folder(tmp_path, "2026-03-18..20 Workshop")
    f2 = _make_folder(tmp_path, "2026-03-19 Workshop")
    (f1 / "notes.txt").write_text("a")
    (f2 / "notes.txt").write_text("b")
    os.environ["SESSIONS_FOLDER"] = str(tmp_path)
    sf, sn = find_session_folder(date(2026, 3, 19))
    assert sf == f2  # latest start_date wins


def test_invalid_end_date_skipped(tmp_path):
    _make_folder(tmp_path, "2026-03-19..32 Workshop")  # day 32 invalid
    os.environ["SESSIONS_FOLDER"] = str(tmp_path)
    sf, sn = find_session_folder(date(2026, 3, 19))
    assert sf is None


def test_uses_most_recently_modified_txt(tmp_path):
    import time
    folder = _make_folder(tmp_path, "2026-03-19 Workshop")
    old = folder / "old.txt"
    new = folder / "new.txt"
    old.write_text("old")
    time.sleep(0.01)
    new.write_text("new")
    os.environ["SESSIONS_FOLDER"] = str(tmp_path)
    _, sn = find_session_folder(date(2026, 3, 19))
    assert sn == new
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest test_quiz_core.py -v 2>&1 | head -30
```
Expected: ImportError or FAILED (find_session_folder not defined yet)

- [ ] **Step 3: Add `session_folder`/`session_notes` to `Config` and add `find_session_folder()`**

In `quiz_core.py`, after `topic: Optional[str] = None` in `Config`:

```python
session_folder: Optional[Path] = None
session_notes: Optional[Path] = None
```

Add the import at top (already has `re`, `Path`, `Optional`; add `date` from `datetime`):

```python
from datetime import date
```

Add the function after `config_from_env()`:

```python
_SESSION_FOLDER_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})(?:\.\.(\d{2}(?:-\d{2})?))?[\s_]"
)

MAX_SESSION_NOTES_CHARS = 20_000


def find_session_folder(today: date) -> tuple[Optional[Path], Optional[Path]]:
    """Returns (session_folder, session_notes). Both None if not found."""
    sessions_root_str = os.environ.get(
        "SESSIONS_FOLDER",
        str(Path.home() / "My Drive" / "Cursuri" / "###sesiuni"),
    )
    sessions_root = Path(sessions_root_str).expanduser()
    if not sessions_root.exists() or not sessions_root.is_dir():
        print(f"[session] SESSIONS_FOLDER not found or not a dir: {sessions_root}", file=sys.stderr)
        return None, None

    matches: list[tuple[date, str, Path]] = []
    for entry in sessions_root.iterdir():
        if not entry.is_dir():
            continue
        m = _SESSION_FOLDER_RE.match(entry.name)
        if not m:
            continue
        try:
            start = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        g2 = m.group(2)
        try:
            if g2 is None:
                end = start
            elif "-" in g2:
                mm, dd = g2.split("-")
                end = date(start.year, int(mm), int(dd))
            else:
                end = date(start.year, start.month, int(g2))
        except ValueError:
            print(f"[session] Skipping folder with invalid end date: {entry.name}", file=sys.stderr)
            continue
        if end < start:
            print(f"[session] Skipping folder where end < start: {entry.name}", file=sys.stderr)
            continue
        if start <= today <= end:
            matches.append((start, entry.name, entry))

    if not matches:
        return None, None

    if len(matches) > 1:
        print(f"[session] Multiple session folders match today: {[m[1] for m in matches]}", file=sys.stderr)

    # Latest start_date; tie-break: alphabetically last name
    matches.sort(key=lambda x: (x[0], x[1]))
    _, _, session_folder = matches[-1]

    # Find most recently modified .txt file
    txt_files = sorted(
        [f for f in session_folder.iterdir() if f.suffix.lower() == ".txt"],
        key=lambda f: f.stat().st_mtime,
    )
    session_notes = txt_files[-1] if txt_files else None

    return session_folder, session_notes
```

- [ ] **Step 4: Run tests**

```bash
pytest test_quiz_core.py -v
```
Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
git add quiz_core.py test_quiz_core.py
git commit -m "feat: add find_session_folder() and Config session fields"
```

---

### Task 2: Add `read_session_notes()` and inject into `auto_generate` / `auto_generate_topic`

**Files:**
- Modify: `quiz_core.py` (new helper + update two functions)
- Modify: `test_quiz_core.py` (add test for `read_session_notes`)

- [ ] **Step 1: Write failing tests**

Add to `test_quiz_core.py`:

```python
from quiz_core import read_session_notes, Config
from pathlib import Path
import dataclasses


def _make_config(tmp_path, notes_path=None):
    return Config(
        folder=tmp_path,
        minutes=30,
        server_url="http://localhost:8000",
        api_key="test",
        model="claude-sonnet-4-6",
        dry_run=True,
        host_username="host",
        host_password="pass",
        session_notes=notes_path,
    )


def test_read_session_notes_returns_content(tmp_path):
    notes = tmp_path / "notes.txt"
    notes.write_text("agenda content", encoding="utf-8")
    config = _make_config(tmp_path, notes)
    result = read_session_notes(config)
    assert result == "agenda content"


def test_read_session_notes_none_returns_empty(tmp_path):
    config = _make_config(tmp_path, None)
    assert read_session_notes(config) == ""


def test_read_session_notes_truncates_from_start(tmp_path):
    notes = tmp_path / "notes.txt"
    # Write content longer than 20_000 chars
    notes.write_text("A" * 5000 + "B" * 20000, encoding="utf-8")
    config = _make_config(tmp_path, notes)
    result = read_session_notes(config)
    assert len(result) == 20000
    assert result == "B" * 20000  # kept the end (most recent)
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest test_quiz_core.py::test_read_session_notes_returns_content -v
```
Expected: ImportError or FAILED

- [ ] **Step 3: Implement `read_session_notes()`**

Add to `quiz_core.py` after `find_session_folder()`:

```python
def read_session_notes(config: "Config") -> str:
    """Read and return session notes content, or '' on failure/missing."""
    if not config.session_notes:
        return ""
    try:
        content = config.session_notes.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        print(f"[session] Could not read notes file: {e}", file=sys.stderr)
        return ""
    if len(content) > MAX_SESSION_NOTES_CHARS:
        print(
            f"[session] Notes file too large ({len(content):,} chars), "
            f"truncating to last {MAX_SESSION_NOTES_CHARS:,} chars.",
            file=sys.stderr,
        )
        content = content[-MAX_SESSION_NOTES_CHARS:]
    return content
```

- [ ] **Step 4: Run tests**

```bash
pytest test_quiz_core.py -v
```
Expected: All PASSED

- [ ] **Step 5: Update `auto_generate()` to inject notes into prompt**

Replace the section in `auto_generate()` that assembles `text` and calls `generate_quiz`:

Before (existing pattern):
```python
    text = extract_last_n_minutes(entries, minutes)
    if not text:
        post_status("error", "Extracted text is empty.", config)
        return None

    line_count = len([l for l in text.splitlines() if l.strip()])
    post_status("generating", f"Sending {len(text):,} chars ({line_count} lines, last {minutes} min) to Claude…", config)

    try:
        quiz = generate_quiz(text, config)
```

After:
```python
    text = extract_last_n_minutes(entries, minutes)
    notes_content = read_session_notes(config)

    if not text and not notes_content:
        post_status("error", "No transcript or session notes available.", config)
        return None

    parts = []
    if notes_content:
        parts.append(f"SESSION NOTES (trainer's written agenda/key points — treat as primary source):\n{notes_content}")
    if text:
        parts.append(f"TRANSCRIPT EXCERPT (last {minutes} min of live audio — use for context and recent topics):\n{text}")
    prompt_content = "\n\n".join(parts)

    line_count = len([l for l in text.splitlines() if l.strip()]) if text else 0
    post_status("generating", f"Sending {len(prompt_content):,} chars ({line_count} lines, last {minutes} min) to Claude…", config)

    try:
        quiz = generate_quiz(prompt_content, config)
```

Also update the `return` line at the end of `auto_generate` to still return `(quiz, text)` — the `last_text` is used by `auto_refine`, so we keep passing only the raw transcript text (not the full prompt).

- [ ] **Step 6: Update `auto_generate_topic()` to inject notes**

Replace in `auto_generate_topic()`:

Before:
```python
    topic_config = replace(config, topic=topic)
    try:
        quiz = generate_quiz("", topic_config)
```

After:
```python
    notes_content = read_session_notes(config)
    if notes_content:
        topic_prompt = f"TOPIC: {topic}\n\nSESSION NOTES (trainer's written agenda/key points — treat as primary source):\n{notes_content}"
    else:
        topic_prompt = ""
    topic_config = replace(config, topic=topic)
    try:
        quiz = generate_quiz(topic_prompt, topic_config)
```

- [ ] **Step 7: Run all existing tests to check nothing is broken**

```bash
pytest test_quiz_core.py test_main.py -v
```
Expected: All PASSED

- [ ] **Step 8: Commit**

```bash
git add quiz_core.py test_quiz_core.py
git commit -m "feat: inject session notes into quiz generation prompts"
```

---

### Task 3: Daemon startup detection and re-detection; extend status payload

**Files:**
- Modify: `quiz_daemon.py`

- [ ] **Step 1: Update `run()` in `quiz_daemon.py`**

After `config = config_from_env()` at daemon startup, add:

```python
    from quiz_core import find_session_folder
    from datetime import date as _date
    sf, sn = find_session_folder(_date.today())
    config = replace(config, session_folder=sf, session_notes=sn)
    if sf:
        print(f"[daemon] Session folder: {sf.name}")
        if sn:
            print(f"[daemon] Session notes: {sn.name}")
        else:
            print("[daemon] Session folder found but no notes file.")
    else:
        print("[daemon] No matching session folder for today.")
```

Add at the top of the `while True:` loop (before the `_get_json` call), after the existing `timestamp_appender.tick()`:

```python
            # Re-detect session folder when the date changes
            if _date.today() != last_detected_date:
                sf, sn = find_session_folder(_date.today())
                config = replace(config, session_folder=sf, session_notes=sn)
                last_detected_date = _date.today()
```

Add `last_detected_date: Optional[date] = None` as a local variable before `while True:` (import `date` is already imported via `find_session_folder`; `replace` is already imported from `dataclasses`).

Also update the `POST /api/quiz-status` call in `quiz_core.post_status` — wait, per the spec the daemon should include `session_folder`/`session_notes` in the **daemon's** status poll call, not every `post_status`. Looking at the spec again: the fields go on `POST /api/quiz-status`. The daemon calls this via `post_status()` in `quiz_core.py`. But the spec says to extend the daemon status payload — the cleanest place is to have the daemon call `POST /api/quiz-status` with these fields.

Per spec section 3: fields included in `POST /api/quiz-status` payload. The daemon needs to pass them. The `post_status()` helper in `quiz_core.py` must accept and forward them.

Update `post_status()` in `quiz_core.py`:

```python
def post_status(status: str, message: str, config: Config) -> None:
    payload = {"status": status, "message": message}
    if config.session_folder is not None:
        payload["session_folder"] = Path(config.session_folder).name
    if config.session_notes is not None:
        payload["session_notes"] = Path(config.session_notes).name
    try:
        _post_json(f"{config.server_url}/api/quiz-status",
                   payload,
                   config.host_username, config.host_password)
    except RuntimeError as e:
        print(f"[warn] Could not post status: {e}", file=sys.stderr)
```

- [ ] **Step 2: Run tests (no new failures expected)**

```bash
pytest test_main.py test_quiz_core.py -v
```
Expected: All PASSED

- [ ] **Step 3: Commit**

```bash
git add quiz_daemon.py quiz_core.py
git commit -m "feat: daemon detects session folder on startup and re-detects on date change"
```

---

### Task 4: Backend — state, router, messaging

**Files:**
- Modify: `state.py`
- Modify: `routers/quiz.py`
- Modify: `messaging.py`

- [ ] **Step 1: Add fields to `AppState` in `state.py`**

In `AppState.reset()`, add after `self.daemon_last_seen`:

```python
        self.daemon_session_folder: Optional[str] = None
        self.daemon_session_notes: Optional[str] = None
```

Also add the field declarations at the class level (follow existing pattern; they are set inside `reset()` so no separate class-level needed — but check existing fields; `state.py` sets them only inside `reset()`).

- [ ] **Step 2: Extend `QuizStatus` model and handler in `routers/quiz.py`**

Add optional fields to `QuizStatus`:

```python
class QuizStatus(BaseModel):
    status: str
    message: str = ""
    session_folder: Optional[str] = None
    session_notes: Optional[str] = None
```

Update `update_quiz_status`:

```python
@router.post("/api/quiz-status")
async def update_quiz_status(body: QuizStatus):
    state.quiz_status = {"status": body.status, "message": body.message}
    if body.session_folder is not None:
        state.daemon_session_folder = body.session_folder
    if body.session_notes is not None:
        state.daemon_session_notes = body.session_notes
    await broadcast({"type": "quiz_status", **state.quiz_status})
    return {"ok": True}
```

Note: fields are optional — old daemon format (without them) leaves stored values unchanged. This backward-compat means existing tests keep working.

- [ ] **Step 3: Include in `build_state_message()` in `messaging.py`**

Add two fields to the returned dict in `build_state_message()`:

```python
        "daemon_session_folder": state.daemon_session_folder,
        "daemon_session_notes": state.daemon_session_notes,
```

- [ ] **Step 4: Run tests**

```bash
pytest test_main.py -v
```
Expected: All PASSED (existing tests shouldn't break; new fields are `None` by default)

- [ ] **Step 5: Commit**

```bash
git add state.py routers/quiz.py messaging.py
git commit -m "feat: store and broadcast daemon_session_folder/notes in state and WS messages"
```

---

### Task 5: Host UI — Agent badge color and tooltip

**Files:**
- Modify: `static/host.js`

- [ ] **Step 1: Update `renderDaemonStatus` call to pass new fields**

In the `handleState` function (around line 147), update the call:

```javascript
renderDaemonStatus(msg.daemon_connected, msg.daemon_last_seen, msg.daemon_session_folder, msg.daemon_session_notes);
```

- [ ] **Step 2: Update `renderDaemonStatus` function signature and logic**

Replace the existing function (lines 189–212) with:

```javascript
  function renderDaemonStatus(connected, lastSeenIso, sessionFolder, sessionNotes) {
    const el = document.getElementById('daemon-badge');
    if (!el) return;
    if (!lastSeenIso) {
      el.textContent = '● Agent';
      el.className = 'badge disconnected';
      el.style.cssText = '';
      el.title = 'Agent: never connected';
      return;
    }
    const ago = Math.round((Date.now() - new Date(lastSeenIso)) / 1000);
    const agoText = ago < 60 ? `${ago}s` : `${Math.round(ago/60)}m`;
    if (connected) {
      el.textContent = '● Agent';
      if (sessionFolder && sessionNotes) {
        el.className = 'badge connected';
        el.style.cssText = '';
        el.title = sessionFolder;
      } else if (sessionFolder) {
        el.className = 'badge';
        el.style.cssText = 'color:var(--warn);border:1px solid var(--warn);';
        el.title = 'Session folder found but no notes file';
      } else {
        el.className = 'badge';
        el.style.cssText = 'color:var(--warn);border:1px solid var(--warn);';
        el.title = 'No session folder found for today';
      }
    } else {
      el.textContent = '● Agent';
      el.className = 'badge';
      el.style.cssText = 'color:var(--warn);border:1px solid var(--warn);';
      el.title = `Agent idle (last seen ${agoText} ago)`;
    }
  }
```

- [ ] **Step 3: Run e2e tests**

```bash
pytest test_e2e.py -v -s --tb=short -k "daemon or agent or badge" 2>&1 | head -40
```
(No e2e tests exist for the badge yet — just verify no other tests regressed)

```bash
pytest test_e2e.py -v -s --tb=short 2>&1 | tail -20
```
Expected: no new failures

- [ ] **Step 4: Commit**

```bash
git add static/host.js
git commit -m "feat: Agent badge shows session folder/notes status with color and tooltip"
```

---

### Task 6: End-to-end smoke test and push

- [ ] **Step 1: Run all tests**

```bash
pytest test_main.py test_quiz_core.py -v && node test_participant_js.js
```
Expected: All PASSED

- [ ] **Step 2: Run e2e tests**

```bash
pytest test_e2e.py -v -s --tb=short
```
Expected: All PASSED

- [ ] **Step 3: Mark backlog item done and push**

In `backlog.md`, mark item #93 as `[x]`.

```bash
git add backlog.md
git commit -m "chore: mark session notes integration as done in backlog"
git push
```

- [ ] **Step 4: Start deploy watcher**

```bash
bash wait-for-deploy.sh &
```
