# Feedback Form Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On the last day of a training session, automatically clone the freeonlinesurveys feedback form, retitle it for this session, and deliver its link to chat, `ai-summary.md`, and every connected participant.

**Architecture:** A `feedback-form` skill drives Claude in Chrome against Victor's already-authenticated Chrome profile to clone + publish the FOS form. It POSTs the resulting URL to the daemon on `127.0.0.1:1234/feedback-form`, which persists it to the session folder, publishes it in shared state, and broadcasts it to participants. `static/participant.html` reveals a left-nav item and a dismissible CTA, both modelled on the existing `#gdrive-row` Google Drive pattern.

**Tech Stack:** Python 3.12 · FastAPI + Pydantic · vanilla JS (no build step) · pytest · Playwright/Docker for hermetic E2E · Claude in Chrome for the browser half.

## Global Constraints

- **Two repos.** Tasks 1–6 land in `training-assistant`. Tasks 7–9 land in `~/workspace/ai` (repo `victorrentea/ai`); after editing there, `cd ~/workspace/ai && git add skills/<name> && git commit && git push`.
- **English only** for all code, comments, identifiers, commit messages, and docs.
- **Push directly to `master`** after each task. Never `main`. Fetch/rebase before pushing.
- **No `railway/**` changes.** The new WS message rides the generic `broadcast` envelope; touching `railway/**` would trigger an unnecessary Railway deploy.
- **Never edit `API.md` by hand.** Regenerate: `python3 scripts/generate_apis_md.py --output API.md`.
- **Pydantic contracts**, never raw dicts, for daemon APIs and WS messages.
- **Daemon logging** follows `daemon/log.py`; arrow geography is directional from the daemon: `↑`/`↓` for railway/participants, `←`/`→` for host.
- **Daemon test isolation:** daemon-only runs need `--confcutdir=tests/daemon`.
- **Slow hermetic tests (>5s)** must be tagged `@pytest.mark.nightly`.
- Full check: `uv run --extra dev --extra daemon --extra telemetry bash tests/check-all.sh` (prefix `arch -arm64` on Apple Silicon).

**Merge hazard:** at plan time another session had uncommitted edits to `daemon/__main__.py`, `daemon/host_server.py`, `daemon/upload.py`, `daemon/slides/router.py` and the railway upload/ws routers. Task 4 touches `daemon/__main__.py`. Check `git status` before starting Task 4 and coordinate if those edits are still in flight.

## File Structure

| File | Responsibility |
|---|---|
| `daemon/misc/feedback_form.py` (create) | Read/write `<session folder>/feedback-form.json`. The only place that knows the file format. |
| `daemon/session/state.py` (modify) | Add `_feedback_url` + getter/setter, mirroring `_gdrive_url`. |
| `daemon/ws_messages.py` (modify) | `FeedbackFormUpdatedMsg` + registry/category entries. |
| `docs/participant-ws.yaml` (modify) | AsyncAPI source of truth for the new message. |
| `daemon/misc/router.py` (modify) | `POST /feedback-form` on the host-local router. |
| `daemon/participant/router.py` (modify) | `feedback_url` in the participant state payload. |
| `daemon/__main__.py` (modify) | Boot-time restore of `feedback_url` from the session folder. |
| `static/participant.html` (modify) | Left-nav item + dismissible CTA. |
| `tests/daemon/test_feedback_form.py` (create) | Unit tests for persistence + endpoint. |
| `tests/docker/test_feedback_form_e2e.py` (create) | Hermetic E2E incl. restart survival. |
| `~/workspace/ai/skills/feedback-form/session_folder.py` (create) | Title derivation + last-day detection. Pure functions, no I/O. |
| `~/workspace/ai/skills/feedback-form/test_session_folder.py` (create) | Tests for the above. |
| `~/workspace/ai/skills/feedback-form/SKILL.md` (create) | The Chrome flow + failure contract. |
| `~/workspace/ai/skills/training-summarizer/SKILL.md` (modify) | Launch the feedback-form sub-agent in Step 5. |

---

### Task 1: Feedback form persistence + shared state

**Files:**
- Create: `daemon/misc/feedback_form.py`
- Modify: `daemon/session/state.py`
- Test: `tests/daemon/test_feedback_form.py`

**Interfaces:**
- Consumes: `daemon.misc.content_files.get_active_session_folder() -> Path | None`
- Produces:
  - `daemon.misc.feedback_form.FEEDBACK_FORM_FILE: str = "feedback-form.json"`
  - `daemon.misc.feedback_form.save_feedback_form(folder: Path, title: str, url: str) -> str` — writes the file, returns the ISO `created_at` it stamped
  - `daemon.misc.feedback_form.load_feedback_form(folder: Path) -> dict | None` — `{"title", "url", "created_at"}` or `None`
  - `daemon.session.state.set_feedback_url(url: str | None) -> None`
  - `daemon.session.state.get_feedback_url() -> str | None`

- [ ] **Step 1: Write the failing test**

Create `tests/daemon/test_feedback_form.py`:

```python
"""Feedback form persistence + shared state."""
import json

from daemon.misc.feedback_form import (
    FEEDBACK_FORM_FILE,
    load_feedback_form,
    save_feedback_form,
)
from daemon.session import state as session_shared_state


def test_save_then_load_roundtrip(tmp_path):
    created_at = save_feedback_form(tmp_path, "AI@Acme", "https://freeonlinesurveys.com/s/demo1234")
    loaded = load_feedback_form(tmp_path)
    assert loaded == {
        "title": "AI@Acme",
        "url": "https://freeonlinesurveys.com/s/demo1234",
        "created_at": created_at,
    }


def test_save_writes_readable_json_at_known_filename(tmp_path):
    save_feedback_form(tmp_path, "DDD@ING", "https://freeonlinesurveys.com/s/abc123")
    on_disk = json.loads((tmp_path / FEEDBACK_FORM_FILE).read_text(encoding="utf-8"))
    assert on_disk["url"] == "https://freeonlinesurveys.com/s/abc123"


def test_load_returns_none_when_absent(tmp_path):
    assert load_feedback_form(tmp_path) is None


def test_load_returns_none_on_corrupt_file(tmp_path):
    (tmp_path / FEEDBACK_FORM_FILE).write_text("{not json", encoding="utf-8")
    assert load_feedback_form(tmp_path) is None


def test_save_overwrites_previous_form(tmp_path):
    save_feedback_form(tmp_path, "Old", "https://freeonlinesurveys.com/s/old")
    save_feedback_form(tmp_path, "New", "https://freeonlinesurveys.com/s/new")
    assert load_feedback_form(tmp_path)["title"] == "New"


def test_shared_state_roundtrip():
    try:
        assert session_shared_state.get_feedback_url() is None
        session_shared_state.set_feedback_url("https://freeonlinesurveys.com/s/demo1234")
        assert session_shared_state.get_feedback_url() == "https://freeonlinesurveys.com/s/demo1234"
        session_shared_state.set_feedback_url(None)
        assert session_shared_state.get_feedback_url() is None
    finally:
        session_shared_state.set_feedback_url(None)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --extra dev --extra daemon python -m pytest tests/daemon/test_feedback_form.py -v --confcutdir=tests/daemon`
Expected: FAIL — `ModuleNotFoundError: No module named 'daemon.misc.feedback_form'`

- [ ] **Step 3: Create the persistence module**

Create `daemon/misc/feedback_form.py`:

```python
"""Persistence for the end-of-session participant feedback form.

The published FOS form URL lives in the session folder rather than only in
memory: the daemon auto-restarts on every push to master, and an in-memory-only
URL would silently disappear from participant screens mid-session.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from daemon import log

FEEDBACK_FORM_FILE = "feedback-form.json"


def save_feedback_form(folder: Path, title: str, url: str) -> str:
    """Write the published form to the session folder. Returns the ISO created_at."""
    created_at = datetime.now(timezone.utc).isoformat()
    payload = {"title": title, "url": url, "created_at": created_at}
    (folder / FEEDBACK_FORM_FILE).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return created_at


def load_feedback_form(folder: Path) -> dict | None:
    """Read the persisted form, or None if absent/unreadable."""
    path = folder / FEEDBACK_FORM_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.error("session", f"Unreadable {FEEDBACK_FORM_FILE}: {e}")
        return None
    if not isinstance(data, dict) or not data.get("url"):
        return None
    return {
        "title": data.get("title", ""),
        "url": data["url"],
        "created_at": data.get("created_at", ""),
    }
```

- [ ] **Step 4: Add the shared-state accessors**

In `daemon/session/state.py`, after the `_gdrive_url` declaration (line 15) add:

```python
_feedback_url: str | None = None
```

After `set_gdrive_url` add:

```python
def set_feedback_url(url: str | None) -> None:
    """Called whenever the active session's participant feedback form URL changes."""
    global _feedback_url
    with _lock:
        _feedback_url = url
```

After `get_gdrive_url` add:

```python
def get_feedback_url() -> str | None:
    with _lock:
        return _feedback_url
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run --extra dev --extra daemon python -m pytest tests/daemon/test_feedback_form.py -v --confcutdir=tests/daemon`
Expected: PASS — 6 passed

- [ ] **Step 6: Commit and push**

```bash
git add daemon/misc/feedback_form.py daemon/session/state.py tests/daemon/test_feedback_form.py
git commit -m "feat(feedback-form): persist the published form URL in the session folder

The daemon restarts on every push to master, so an in-memory-only URL would
vanish from participant screens mid-session."
git fetch origin && git rebase origin/master && git push origin master
```

---

### Task 2: WS message contract

**Files:**
- Modify: `daemon/ws_messages.py`
- Modify: `docs/participant-ws.yaml`
- Test: `tests/daemon/test_ws_contract.py` (existing — must keep passing)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `daemon.ws_messages.FeedbackFormUpdatedMsg` with fields `type: Literal["feedback_form_updated"]` and `feedback_url: str | None = None`.

- [ ] **Step 1: Add the message model**

In `daemon/ws_messages.py`, immediately after `AgendaUpdatedMsg` (~line 353) add:

```python
class FeedbackFormUpdatedMsg(BaseModel):
    """Participant-only: the end-of-session feedback form link is available.

    Sent when the form is published (or cleared with None at session teardown).
    """
    type: Literal["feedback_form_updated"] = "feedback_form_updated"
    feedback_url: str | None = None  # published FOS survey URL, None when cleared
```

- [ ] **Step 2: Register it in the participant registry and category map**

In `PARTICIPANT_MESSAGES`, directly under `"agenda_updated": AgendaUpdatedMsg,` add:

```python
    "feedback_form_updated": FeedbackFormUpdatedMsg,
```

In the participant category map, directly under `"agenda_updated": "notes_summary",` add:

```python
    "feedback_form_updated": "notes_summary",
```

Do **not** add it to `HOST_MESSAGES` — the host learns nothing new from it.

- [ ] **Step 3: Add it to the AsyncAPI source of truth**

In `docs/participant-ws.yaml`, in the `oneOf` list, after the `agenda_updated` `$ref` (~line 48) add:

```yaml
          - $ref: '#/components/messages/feedback_form_updated'
```

Then in `components.messages`, after the `notes_updated` block, add:

```yaml
    feedback_form_updated:
      summary: End-of-session participant feedback form link published
      x-feature: notes_summary
      payload:
        type: object
        required: [type]
        properties:
          type:
            type: string
            enum: [feedback_form_updated]
          feedback_url:
            type: string
            nullable: true
            description: Published freeonlinesurveys URL, or null when cleared
```

- [ ] **Step 4: Run the contract test**

Run: `uv run --extra dev --extra daemon python -m pytest tests/daemon/test_ws_contract.py -v --confcutdir=tests/daemon`
Expected: PASS — the registry and the YAML agree.

- [ ] **Step 5: Commit and push**

```bash
git add daemon/ws_messages.py docs/participant-ws.yaml
git commit -m "feat(feedback-form): add feedback_form_updated participant WS message

Rides the generic broadcast envelope, so Railway relays it without knowing
the event type and no railway/** deploy is needed."
git fetch origin && git rebase origin/master && git push origin master
```

---

### Task 3: The host-local POST endpoint

**Files:**
- Modify: `daemon/misc/router.py`
- Modify: `docs/openapi.yaml` (regenerated)
- Modify: `API.md` (regenerated)
- Test: `tests/daemon/test_feedback_form.py` (extend)

**Interfaces:**
- Consumes: `save_feedback_form`, `set_feedback_url` (Task 1); `FeedbackFormUpdatedMsg` (Task 2).
- Produces: `POST /feedback-form` on `local_router`, request `FeedbackFormRequest{title: str, url: str}`, response `FeedbackFormResponse{title: str, url: str, created_at: str}`.

The endpoint goes on `local_router` (`daemon/misc/router.py:284`), the host-machine-only router with **no `{session_id}` in the path** — the same choice `/summary/highlight` made, for the same reason: the daemon serves a single active session and resolves the folder itself. The caller is a local skill on `127.0.0.1:1234`, never a participant browser.

- [ ] **Step 1: Write the failing test**

Append to `tests/daemon/test_feedback_form.py`:

```python
def test_post_feedback_form_persists_broadcasts_and_publishes(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from daemon.misc import router as misc_router

    sent = []
    monkeypatch.setattr(misc_router, "broadcast", lambda msg: sent.append(msg))
    monkeypatch.setattr(misc_router, "get_active_session_folder", lambda: tmp_path)

    app = FastAPI()
    app.include_router(misc_router.local_router)
    client = TestClient(app)
    try:
        resp = client.post(
            "/feedback-form",
            json={"title": "AI@Acme", "url": "https://freeonlinesurveys.com/s/demo1234"},
        )
        assert resp.status_code == 200
        assert resp.json()["url"] == "https://freeonlinesurveys.com/s/demo1234"

        # persisted for restart survival
        assert load_feedback_form(tmp_path)["title"] == "AI@Acme"
        # published to participants joining later
        assert session_shared_state.get_feedback_url() == "https://freeonlinesurveys.com/s/demo1234"
        # pushed to participants already connected
        assert len(sent) == 1
        assert sent[0].type == "feedback_form_updated"
        assert sent[0].feedback_url == "https://freeonlinesurveys.com/s/demo1234"
    finally:
        session_shared_state.set_feedback_url(None)


def test_post_feedback_form_404_without_active_session(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from daemon.misc import router as misc_router

    monkeypatch.setattr(misc_router, "get_active_session_folder", lambda: None)
    app = FastAPI()
    app.include_router(misc_router.local_router)
    resp = TestClient(app).post(
        "/feedback-form",
        json={"title": "AI@Acme", "url": "https://freeonlinesurveys.com/s/demo1234"},
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --extra dev --extra daemon python -m pytest tests/daemon/test_feedback_form.py -v --confcutdir=tests/daemon`
Expected: FAIL — 404 on an unregistered route / `AttributeError` on the missing handler.

- [ ] **Step 3: Implement the endpoint**

In `daemon/misc/router.py`, extend the existing imports:

```python
from daemon.misc.feedback_form import save_feedback_form
from daemon.session import state as session_shared_state
from daemon.ws_messages import FeedbackFormUpdatedMsg, PasteReceivedMsg, SummaryUpdatedMsg
```

Then, after the `highlight_summary_local` handler, add:

```python
class FeedbackFormRequest(BaseModel):
    title: str
    url: str


class FeedbackFormResponse(BaseModel):
    title: str
    url: str
    created_at: str


@local_router.post("/feedback-form", response_model=FeedbackFormResponse)
async def publish_feedback_form(body: FeedbackFormRequest):
    """Publish the end-of-session participant feedback form link.

    Host-machine-local, like /summary/highlight: called by the feedback-form
    skill on 127.0.0.1 once the FOS survey is cloned, retitled and published.
    """
    folder = get_active_session_folder()
    if folder is None:
        return JSONResponse(status_code=404, content={"detail": "no active session"})
    title = body.title.strip()
    url = body.url.strip()
    if not url:
        return JSONResponse(status_code=400, content={"detail": "url is required"})
    created_at = await asyncio.to_thread(save_feedback_form, folder, title, url)
    session_shared_state.set_feedback_url(url)
    logger.info("Feedback form: %s (%s)", url, title)
    broadcast(FeedbackFormUpdatedMsg(feedback_url=url))  # participants reveal the nav item
    return FeedbackFormResponse(title=title, url=url, created_at=created_at)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --extra dev --extra daemon python -m pytest tests/daemon/test_feedback_form.py -v --confcutdir=tests/daemon`
Expected: PASS — 8 passed

- [ ] **Step 5: Regenerate the API contract snapshots**

```bash
uv run --extra dev --extra daemon python -m tests.daemon.test_api_contract --regenerate
python3 scripts/generate_apis_md.py --output API.md
```

- [ ] **Step 6: Verify the contract test agrees**

Run: `uv run --extra dev --extra daemon python -m pytest tests/daemon/test_api_contract.py -v --confcutdir=tests/daemon`
Expected: PASS

- [ ] **Step 7: Commit and push**

```bash
git add daemon/misc/router.py docs/openapi.yaml API.md tests/daemon/test_feedback_form.py
git commit -m "feat(feedback-form): POST /feedback-form publishes the form to participants

Host-local route with no session_id, matching /summary/highlight: the daemon
serves one active session and resolves the folder itself."
git fetch origin && git rebase origin/master && git push origin master
```

---

### Task 4: Serve it on load and restore it at boot

**Files:**
- Modify: `daemon/participant/router.py:322` (model) and `:909` (payload)
- Modify: `daemon/__main__.py` (~line 1026, the boot-time gdrive block)
- Test: `tests/daemon/test_feedback_form.py` (extend)

**Interfaces:**
- Consumes: `session_shared_state.get_feedback_url()` (Task 1), `load_feedback_form` (Task 1).
- Produces: `feedback_url: str | None` in the participant state payload.

**Before starting:** run `git status` and confirm nobody else is mid-edit in `daemon/__main__.py` (see the merge hazard note in Global Constraints).

- [ ] **Step 1: Write the failing test**

Append to `tests/daemon/test_feedback_form.py`:

```python
def test_participant_state_payload_carries_feedback_url():
    """A participant loading or reconnecting mid-session must see the link."""
    from daemon.participant.router import ParticipantState

    assert "feedback_url" in ParticipantState.model_fields
    field = ParticipantState.model_fields["feedback_url"]
    assert field.default is None


def test_boot_restore_reads_url_from_session_folder(tmp_path):
    """The daemon restarts on every push to master — the link must come back."""
    save_feedback_form(tmp_path, "AI@Acme", "https://freeonlinesurveys.com/s/demo1234")
    session_shared_state.set_feedback_url(None)  # simulate a fresh process
    try:
        restored = load_feedback_form(tmp_path)
        session_shared_state.set_feedback_url(restored["url"] if restored else None)
        assert session_shared_state.get_feedback_url() == "https://freeonlinesurveys.com/s/demo1234"
    finally:
        session_shared_state.set_feedback_url(None)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --extra dev --extra daemon python -m pytest tests/daemon/test_feedback_form.py -v --confcutdir=tests/daemon`
Expected: FAIL — `assert "feedback_url" in ParticipantState.model_fields`

- [ ] **Step 3: Add the field to the participant state model**

In `daemon/participant/router.py`, directly under `gdrive_url: str | None = None` (line 322):

```python
    feedback_url: str | None = None
```

- [ ] **Step 4: Populate it in the state payload**

In the same file, directly under the `"gdrive_url": session_shared_state.get_gdrive_url(),` entry (line 909):

```python
        # End-of-session participant feedback form (freeonlinesurveys)
        "feedback_url": session_shared_state.get_feedback_url(),
```

- [ ] **Step 5: Restore it at daemon boot**

In `daemon/__main__.py`, immediately after the boot-time GDrive block that ends with the `"Google Drive not available at boot…"` log line, add:

```python
    # Boot-time feedback form restore. Unlike gdrive_url (cheap to re-resolve
    # from DriveFS) this URL exists only where we wrote it, so it is read back
    # from the session folder — the daemon restarts on every push to master and
    # participants must not lose the link mid-session.
    if session_name and config.session_folder:
        from daemon.misc.feedback_form import load_feedback_form as _load_feedback_form
        _boot_feedback = _load_feedback_form(config.session_folder)
        if _boot_feedback:
            session_shared_state.set_feedback_url(_boot_feedback["url"])
            log.info("session", f"Feedback form: {_boot_feedback['url']}")
        else:
            session_shared_state.set_feedback_url(None)
```

- [ ] **Step 6: Re-resolve it when the session switches**

`set_gdrive_url` is driven from **four** places in `daemon/__main__.py`, not two. The session-switch site (~line 1250, `session_shared_state.set_gdrive_url(_new_gdrive_url)`, where a session is created or resumed) must be mirrored too — otherwise starting a new session leaves the *previous* client's feedback form live in the new room.

Directly after that `set_gdrive_url(_new_gdrive_url)` / `log.info("session", f"Google Drive: …")` pair, add:

```python
                            # Re-resolve the feedback form for the session being
                            # entered: normally absent (clearing the previous
                            # session's URL), present when resuming a session
                            # whose form was already published.
                            from daemon.misc.feedback_form import (
                                load_feedback_form as _load_feedback_form_switch,
                            )
                            _new_feedback = _load_feedback_form_switch(folder)
                            session_shared_state.set_feedback_url(
                                _new_feedback["url"] if _new_feedback else None
                            )
                            if _new_feedback:
                                log.info("session", f"Feedback form: {_new_feedback['url']}")
```

- [ ] **Step 7: Clear it when the session is torn down**

In `daemon/__main__.py`, find the existing `session_shared_state.set_gdrive_url(None)` teardown call (~line 1335) and add directly beneath it:

```python
                        session_shared_state.set_feedback_url(None)
```

- [ ] **Step 8: Add the session-switch regression test**

Append to `tests/daemon/test_feedback_form.py`:

```python
def test_session_switch_does_not_leak_the_previous_sessions_form(tmp_path):
    """Entering a session with no form must clear the previous session's URL.

    Otherwise one client's feedback form stays live in the next client's room.
    """
    previous = tmp_path / "2026-08-11..13 AI@Acme"
    previous.mkdir()
    save_feedback_form(previous, "AI@Acme", "https://freeonlinesurveys.com/s/old")
    session_shared_state.set_feedback_url("https://freeonlinesurveys.com/s/old")

    entering = tmp_path / "2026-08-20 DDD@ING"
    entering.mkdir()
    try:
        found = load_feedback_form(entering)
        session_shared_state.set_feedback_url(found["url"] if found else None)
        assert session_shared_state.get_feedback_url() is None
    finally:
        session_shared_state.set_feedback_url(None)


def test_session_switch_restores_a_resumed_sessions_form(tmp_path):
    """Re-entering a session whose form was already published restores it."""
    folder = tmp_path / "2026-08-11..13 AI@Acme"
    folder.mkdir()
    save_feedback_form(folder, "AI@Acme", "https://freeonlinesurveys.com/s/demo1234")
    session_shared_state.set_feedback_url(None)
    try:
        found = load_feedback_form(folder)
        session_shared_state.set_feedback_url(found["url"] if found else None)
        assert session_shared_state.get_feedback_url() == "https://freeonlinesurveys.com/s/demo1234"
    finally:
        session_shared_state.set_feedback_url(None)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run --extra dev --extra daemon python -m pytest tests/daemon/test_feedback_form.py -v --confcutdir=tests/daemon`
Expected: PASS — 12 passed

- [ ] **Step 8: Regenerate the API snapshots (the participant state schema changed)**

```bash
uv run --extra dev --extra daemon python -m tests.daemon.test_api_contract --regenerate
python3 scripts/generate_apis_md.py --output API.md
uv run --extra dev --extra daemon python -m pytest tests/daemon/test_api_contract.py -v --confcutdir=tests/daemon
```
Expected: PASS

- [ ] **Step 9: Commit and push**

```bash
git add daemon/participant/router.py daemon/__main__.py docs/openapi.yaml API.md tests/daemon/test_feedback_form.py
git commit -m "feat(feedback-form): serve the link on load and restore it across restarts

Read back from the session folder at boot so a push to master (which restarts
the daemon) does not drop the link from participant screens."
git fetch origin && git rebase origin/master && git push origin master
```

---

### Task 5: Participant UI — nav item and CTA

**Files:**
- Modify: `static/participant.html` (~795 nav, ~3937 state applier, ~4030 broadcast handler, ~4444 message switch)

**Interfaces:**
- Consumes: `state.feedback_url` and `msg.feedback_url` (Task 4), the `feedback_form_updated` message type (Task 2).
- Produces: no interface for later tasks.

Modelled directly on `#gdrive-row`, which is already a hidden nav row revealed by a URL arriving in state or in a broadcast. Note `gdrive_url` is handled in **two** places and the feedback link needs both: the state applier covers fresh loads and reconnects, the broadcast handler covers the live moment the link is published.

**All line numbers in this task are approximate.** That parallel change has now landed (through `7a9b3b44`): `static/participant.html` gained a "Report a bug" nav entry between `data-nav="upload-paste"` and `data-nav="about"`, and the orphaned `#feedback-view` / `sendFeedback()` is deleted. Pull `master` first and locate each anchor by its surrounding markup, not by line number. No collision — `#feedback-row` goes between `#gdrive-row` and `data-nav="files"`.

**`static/vendor/tailwind.css` is a PREBUILT SUBSET and there is no build step.** A class that isn't in that file is a silent no-op — no error, no warning, the style simply doesn't apply. Before using any utility class, verify it exists:

```bash
grep -oE '\.[-a-zA-Z0-9\\:/\[\]%.]+' static/vendor/tailwind.css | sed 's/^\.//; s/\\//g' | sort -u > /tmp/tw.txt
grep -qx 'CLASS-NAME' /tmp/tw.txt && echo PRESENT || echo MISSING
```

This was checked for this task. **Present:** `fixed`, `absolute`, `bottom-6`, `left-1/2`, `rounded-2xl`, `px-5`, `px-4`, `shadow-lg`, `opacity-60`, `font-semibold`, `mb-3`, `text-sm`, `text-base`, `inline-flex`, `gap-2`, `gap-1`, `text-center`, plus every class in the `#gdrive-row` block. **MISSING — do not use:** `z-50`, `max-w-sm`, `py-4`, `top-2`, `right-2`, `mb-1`, `opacity-80`, `-translate-x-1/2`, `w-[92%]`.

Because so much of the CTA's layout vocabulary is absent (including the `-translate-x-1/2` that would center it), **the CTA card below uses inline `style=` for all layout, spacing and color.** The nav row keeps Tailwind classes only because it is a verbatim copy of the working `#gdrive-row`.

**The four-place tab registration does NOT apply here.** A new participant *view* must be registered in four places (`VIEWS`, `_PARTICIPANT_TAB_SLUGS` in `railway/features/pages/router.py`, `_KNOWN_VIEWS` in `daemon/participant/router.py`, `ENGAGEMENT_VIEW_LABELS` in `static/host.js`). `#feedback-row` is **not a view** — it is an external-link row exactly like `#gdrive-row`, with no `data-nav` attribute and no `showView()` call. It must NOT be added to any of those four lists, and it needs no `railway/**` change.

- [ ] **Step 1: Add the hidden nav row**

In `static/participant.html`, directly after the `#gdrive-row` `</div>` (~line 803) and before the `data-nav="files"` anchor, insert:

```html
<div id="feedback-row" class="nav-item rounded-full px-2 py-2 flex items-center gap-3 transition-all" style="display:none">
<a id="feedback-nav" href="#" target="_blank" rel="noopener" class="flex items-center gap-3 flex-1 cursor-pointer">
<span class="material-symbols-outlined flex-shrink-0">rate_review</span>
<span class="text-base flex-1">Feedback form</span>
<span class="material-symbols-outlined flex-shrink-0" style="font-size:1rem;opacity:0.5">open_in_new</span>
</a>
</div>
```

- [ ] **Step 2: Add the CTA card markup**

Directly after the nav row, still inside the page body, add the dismissible CTA:

Layout, spacing and color are inline because the vendored Tailwind subset lacks the classes this needs (see the note above). Colors use the same CSS custom properties the rest of the participant page uses, so the card follows the light/dark theme.

```html
<div id="feedback-cta" role="status" style="display:none;position:fixed;bottom:1.5rem;left:50%;transform:translateX(-50%);z-index:50;width:92%;max-width:24rem;padding:1rem 1.25rem;border-radius:1rem;box-shadow:0 10px 30px rgba(0,0,0,.25);background:var(--surface,#182029);color:var(--text,#e6edf3)">
<button id="feedback-cta-close" onclick="dismissFeedbackCta()" aria-label="Dismiss" class="cursor-pointer" style="position:absolute;top:.5rem;right:.5rem;opacity:.6;background:none;border:none;color:inherit">
<span class="material-symbols-outlined" style="font-size:1.1rem">close</span>
</button>
<p class="font-semibold" style="margin:0 0 .25rem">How was this training?</p>
<p class="text-sm" style="margin:0 0 .75rem;opacity:.8">Two minutes of your feedback shapes the next session.</p>
<a id="feedback-cta-link" href="#" target="_blank" rel="noopener" onclick="dismissFeedbackCta()" class="inline-flex items-center gap-2 font-semibold" style="padding:.5rem 1rem;border-radius:9999px;background:var(--accent,#2563eb);color:#fff;text-decoration:none">
<span class="material-symbols-outlined" style="font-size:1.1rem">rate_review</span>Open the feedback form</a>
</div>
```

Before committing, confirm the two CSS custom properties actually exist in `static/participant-theme.css` / `static/common.css`. If a name differs, use the real one — the `var(--x, fallback)` form means a wrong name fails silently to the fallback, which is exactly the class of bug this whole note exists to prevent.

- [ ] **Step 3: Add the shared apply function**

In the page's script section, next to the other nav helpers, add:

```javascript
/* Feedback form link. Mirrors the gdrive row: one URL drives a permanent
   left-nav entry plus a one-time CTA. The CTA's dismissal is remembered
   locally so a reconnect does not re-nag someone who already answered. */
function _applyFeedbackUrl(url) {
  var row = document.getElementById('feedback-row');
  var nav = document.getElementById('feedback-nav');
  var cta = document.getElementById('feedback-cta');
  var ctaLink = document.getElementById('feedback-cta-link');
  if (!url) {
    row.style.display = 'none';
    cta.style.display = 'none';
    return;
  }
  nav.href = url;
  row.style.display = '';
  ctaLink.href = url;
  var dismissed = false;
  try { dismissed = localStorage.getItem('feedbackCtaDismissed') === url; } catch (e) {}
  cta.style.display = dismissed ? 'none' : '';
}

function dismissFeedbackCta() {
  var cta = document.getElementById('feedback-cta');
  var url = document.getElementById('feedback-cta-link').href;
  cta.style.display = 'none';
  try { localStorage.setItem('feedbackCtaDismissed', url); } catch (e) {}
}
```

- [ ] **Step 4: Wire it into the state applier**

In the state applier, directly after the `_applyGdriveToast(state.gdrive_url);` line (~line 3941), add:

```javascript
    _applyFeedbackUrl(state.feedback_url);
```

- [ ] **Step 5: Wire it into the broadcast handler and the message switch**

After the `_applyGdriveToast(msg.gdrive_url);` line (~line 4034), add:

```javascript
  }
  if (msg.feedback_url !== undefined) {
    _applyFeedbackUrl(msg.feedback_url);
```

(Match the surrounding `if (msg.<field> !== undefined) { … }` brace style exactly — read the block before editing.)

Then in the message-type switch, next to `case 'agenda_updated'`, add:

```javascript
    case 'feedback_form_updated': _applyFeedbackUrl(msg.feedback_url); break;
```

- [ ] **Step 6: Verify in a real browser**

Start the daemon, join as a participant on `http://localhost:8081/`, then publish a link:

```bash
curl -sS -X POST http://127.0.0.1:1234/feedback-form \
  -H 'Content-Type: application/json' \
  -d '{"title":"AI@Acme","url":"https://freeonlinesurveys.com/s/demo1234"}'
```

Expected: the CTA appears immediately without a refresh, and "Feedback form" shows in the left nav. Reload the page: the nav item persists, the CTA stays gone after being dismissed. **Take a screenshot of the left nav and the CTA** — visual changes need visual proof.

- [ ] **Step 7: Commit and push**

```bash
git add static/participant.html
git commit -m "feat(feedback-form): reveal the form in the participant nav and a dismissible CTA

Dismissal is keyed on the URL in localStorage so a reconnect does not re-nag
someone who already answered."
git fetch origin && git rebase origin/master && git push origin master
```

---

### Task 6: Hermetic E2E

**Files:**
- Create: `tests/docker/test_feedback_form_e2e.py`

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces: no interface for later tasks.

Read `TESTING.md` and an existing `tests/docker/` test first, and copy its fixtures verbatim — the hermetic harness owns backend + daemon + Playwright startup, and hand-rolling it is the usual way these tests flake.

- [ ] **Step 1: Write the E2E test**

Create `tests/docker/test_feedback_form_e2e.py`, using the same fixtures as the neighbouring docker tests:

```python
"""Hermetic E2E: the feedback form link reaches participants and survives a restart."""
import pytest


@pytest.mark.nightly
def test_feedback_link_appears_live_without_reload(hermetic_stack, participant_page):
    """Publishing the form reveals the nav item on an already-connected participant."""
    assert participant_page.locator("#feedback-row").is_hidden()

    hermetic_stack.daemon_post(
        "/feedback-form",
        {"title": "AI@Acme", "url": "https://freeonlinesurveys.com/s/demo1234"},
    )

    participant_page.wait_for_selector("#feedback-row:visible", timeout=5000)
    assert participant_page.locator("#feedback-nav").get_attribute("href") == (
        "https://freeonlinesurveys.com/s/demo1234"
    )
    participant_page.wait_for_selector("#feedback-cta:visible", timeout=5000)


@pytest.mark.nightly
def test_feedback_link_survives_daemon_restart(hermetic_stack, participant_page):
    """The regression this feature exists to prevent: a push to master restarts
    the daemon, and the link must still be there afterwards."""
    hermetic_stack.daemon_post(
        "/feedback-form",
        {"title": "AI@Acme", "url": "https://freeonlinesurveys.com/s/demo1234"},
    )
    participant_page.wait_for_selector("#feedback-row:visible", timeout=5000)

    hermetic_stack.restart_daemon()

    participant_page.reload()
    participant_page.wait_for_selector("#feedback-row:visible", timeout=10000)
    assert participant_page.locator("#feedback-nav").get_attribute("href") == (
        "https://freeonlinesurveys.com/s/demo1234"
    )
```

Adapt `hermetic_stack.daemon_post` / `restart_daemon` / `participant_page` to whatever the existing docker conftest actually exposes — do not invent fixtures.

- [ ] **Step 2: Run it in Docker**

Run: `bash tests/docker/run-hermetic.sh -k feedback_form -m nightly -s`
Expected: PASS — both tests green. A hermetic task is not done until it has run in Docker.

- [ ] **Step 3: Run the full check suite**

Run: `uv run --extra dev --extra daemon --extra telemetry bash tests/check-all.sh`
Expected: PASS

- [ ] **Step 4: Commit and push**

```bash
git add tests/docker/test_feedback_form_e2e.py
git commit -m "test(feedback-form): hermetic E2E for live delivery and restart survival"
git fetch origin && git rebase origin/master && git push origin master
```

---

### Task 7: Session folder parsing (repo `victorrentea/ai`)

**Files:**
- Create: `~/workspace/ai/skills/feedback-form/session_folder.py`
- Test: `~/workspace/ai/skills/feedback-form/test_session_folder.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `derive_form_title(folder_name: str) -> str` — folder name minus its date prefix
  - `last_day(folder_name: str) -> date` — the last date the folder name covers
  - `is_last_day(folder_name: str, today: date) -> bool`

Pure functions with no I/O, so they are cheaply testable — the browser half never can be.

- [ ] **Step 1: Write the failing test**

Create `~/workspace/ai/skills/feedback-form/test_session_folder.py`:

```python
"""Title derivation and last-day detection from a session folder name."""
from datetime import date

import pytest

from session_folder import derive_form_title, is_last_day, last_day


@pytest.mark.parametrize("folder,expected", [
    ("2026-08-11..13 AI@Acme", "AI@Acme"),
    ("2026-08-13 AI@Acme", "AI@Acme"),
    ("2026-07-09..10 Spring Boot@ING", "Spring Boot@ING"),
    ("2026-08-13  Extra   Spaces@Client", "Extra   Spaces@Client"),
])
def test_derive_form_title_strips_the_date_prefix(folder, expected):
    assert derive_form_title(folder) == expected


@pytest.mark.parametrize("folder,expected", [
    ("2026-08-11..13 AI@Acme", date(2026, 8, 13)),
    ("2026-08-13 AI@Acme", date(2026, 8, 13)),
    ("2026-08-30..09-02 Long@Client", date(2026, 9, 2)),
])
def test_last_day_handles_single_and_ranged_folders(folder, expected):
    assert last_day(folder) == expected


def test_is_last_day_true_only_on_the_final_date():
    folder = "2026-08-11..13 AI@Acme"
    assert is_last_day(folder, date(2026, 8, 13)) is True
    assert is_last_day(folder, date(2026, 8, 12)) is False
    assert is_last_day(folder, date(2026, 8, 11)) is False


def test_single_date_folder_is_always_its_own_last_day():
    assert is_last_day("2026-08-13 AI@Acme", date(2026, 8, 13)) is True


def test_unparseable_folder_raises():
    with pytest.raises(ValueError):
        last_day("no-date-here AI@Acme")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd ~/workspace/ai/skills/feedback-form && python3 -m pytest test_session_folder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'session_folder'`

- [ ] **Step 3: Implement it**

Create `~/workspace/ai/skills/feedback-form/session_folder.py`:

```python
"""Parse a training session folder name into a form title and its last day.

Folder names look like `YYYY-MM-DD[..DD|..MM-DD] Topic@client`, e.g.
`2026-08-11..13 AI@Acme`. The FOS form title is exactly the `Topic@client`
tail, which is why cloning + retitling can run unattended.
"""
from __future__ import annotations

import re
from datetime import date

_PREFIX = re.compile(
    r"^(?P<start>\d{4}-\d{2}-\d{2})"          # 2026-08-11
    r"(?:\.\.(?P<end>(?:\d{2}-)?\d{2}))?"      # optional ..13 or ..09-02
    r"\s+"
)


def _match(folder_name: str) -> re.Match:
    m = _PREFIX.match(folder_name)
    if not m:
        raise ValueError(f"Not a session folder name: {folder_name!r}")
    return m


def derive_form_title(folder_name: str) -> str:
    """`2026-08-11..13 AI@Acme` -> `AI@Acme`."""
    return folder_name[_match(folder_name).end():].strip()


def last_day(folder_name: str) -> date:
    """The final date the folder covers."""
    m = _match(folder_name)
    start = date.fromisoformat(m.group("start"))
    end = m.group("end")
    if not end:
        return start
    if "-" in end:                      # ..09-02 — the range crosses a month
        month, day = (int(p) for p in end.split("-"))
        return date(start.year, month, day)
    return date(start.year, start.month, int(end))


def is_last_day(folder_name: str, today: date) -> bool:
    return last_day(folder_name) == today
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ~/workspace/ai/skills/feedback-form && python3 -m pytest test_session_folder.py -v`
Expected: PASS — 10 passed (4 + 3 parametrised cases, plus 3 plain tests)

- [ ] **Step 5: Commit and push the skills repo**

```bash
cd ~/workspace/ai
git add skills/feedback-form
git commit -m "feat(feedback-form): derive the FOS form title and the session's last day"
git push
```

---

### Task 8: The feedback-form skill (repo `victorrentea/ai`)

**Files:**
- Create: `~/workspace/ai/skills/feedback-form/SKILL.md`

**Interfaces:**
- Consumes: `session_folder.derive_form_title` (Task 7); `POST 127.0.0.1:1234/feedback-form` (Task 3).
- Produces: a skill invocable as `victor-skills:feedback-form`, returning `{title, url, qr_png_path}` or a structured failure.

- [ ] **Step 1: Write the skill**

Create `~/workspace/ai/skills/feedback-form/SKILL.md`:

````markdown
---
name: feedback-form
description: "Clone the previous freeonlinesurveys feedback form, retitle it for the current training session, publish it, and deliver the link to the participants. Trigger at the end of the last day of a session, or when Victor asks for the feedback form / survey link for a session."
---

# Feedback Form Skill

Creates the end-of-session participant feedback form on
[freeonlinesurveys.com](https://freeonlinesurveys.com) by cloning the previous
one — the same manoeuvre Victor does by hand — and delivers the link.

FOS has no API for *creating* surveys, so this runs through Claude in Chrome
against Victor's real Chrome profile, which already holds the Google SSO
session. **Never attempt to automate the Google login itself.**

## Input

- `session_folder` — absolute path to the session folder.
- Derive the title with `python3 session_folder.py` helpers:
  `derive_form_title("2026-08-11..13 AI@Acme")` → `AI@Acme`.
  **Print the derived title before using it** — this runs unattended, so the
  scrollback is the only record.

## Flow

Load the `claude-in-chrome` skill first, then batch every browser tool you need
into ONE `ToolSearch` call.

1. `tabs_context_mcp` to see the current tabs, then **`tabs_create_mcp` a new
   tab** — never hijack a tab Victor is using.
2. Navigate to the FOS dashboard.
3. **Auth gate.** If a login screen appears, STOP and return the
   `not_authenticated` failure. Do not touch Google SSO.
4. Find the most recently modified survey; invoke its Duplicate/Clone action.
5. Open the clone → **Build** → set the title to the derived title.
6. **Publish it.** An unpublished clone serves no link ("Must be published…"
   on the Send screen). This step is mandatory.
7. **Send → Get a link (URL)** → read the `https://freeonlinesurveys.com/s/…`
   URL.
8. **DOWNLOAD PNG** on the same screen → save to
   `<session_folder>/feedback-qr.png` (for projecting; participants get a
   tappable link, not a QR).
9. POST the result to the daemon:

   ```bash
   curl -sS -X POST http://127.0.0.1:1234/feedback-form \
     -H 'Content-Type: application/json' \
     -d '{"title":"<title>","url":"<url>"}'
   ```

   A non-200 here is **not** a failure of the skill — the link still reaches
   chat and the summary. Report it and continue.
10. Return `{"title": …, "url": …, "qr_png_path": …}`.

## Rules

- **Verify each step by reading the page**, never click blind.
- **Never trigger a native dialog** (`alert`/`confirm`) — it freezes the
  extension and the session cannot recover without Victor dismissing it by hand.
- **Record what worked.** After the first successful run, append the concrete
  selectors and navigation steps to a `## Known flow` section here, so later
  runs are deterministic rather than exploratory.
- **Dry-run mode:** when invoked with `dry-run`, stop after step 5 (retitled,
  unpublished) and report the draft. Use this to exercise the flow without
  creating a live client-facing form.

## Failure

Any failure returns, and never blocks the caller:

```json
{"error": "not_authenticated|clone_failed|publish_failed|link_not_found",
 "detail": "...", "dashboard_url": "...", "title": "<derived title>"}
```

Tell Victor plainly what broke and that the form needs creating by hand. A
missing feedback form is an annoyance; a blocked summary at the end of a
training day is a real failure.
````

- [ ] **Step 2: Verify the skill is discovered**

Run: `ls ~/workspace/ai/skills/feedback-form/SKILL.md && head -3 ~/workspace/ai/skills/feedback-form/SKILL.md`
Expected: the frontmatter `name: feedback-form` is present. It is auto-discovered as `victor-skills:feedback-form` from the local marketplace.

- [ ] **Step 3: Commit and push**

```bash
cd ~/workspace/ai
git add skills/feedback-form/SKILL.md
git commit -m "feat(feedback-form): skill that clones and publishes the FOS feedback form"
git push
```

- [ ] **Step 4: Refresh the Copilot cache**

Run: `copilot plugin update victor-skills`
Expected: the remote marketplace picks up the pushed skill.

---

### Task 9: training-summarizer integration (repo `victorrentea/ai`)

**Files:**
- Modify: `~/workspace/ai/skills/training-summarizer/SKILL.md` (Step 5 fan-out section)

**Interfaces:**
- Consumes: `victor-skills:feedback-form` (Task 8), `session_folder.is_last_day` (Task 7).
- Produces: no interface for later tasks.

- [ ] **Step 1: Add the fan-out bullet**

In `~/workspace/ai/skills/training-summarizer/SKILL.md`, in Step 5's list of detached background sub-agents (alongside "Main takeaways", "Links", "Browsed links"), add:

```markdown
- **Feedback form (last day only, Opus sub-agent).** Run
  `is_last_day(<folder name>, today)` from
  `~/workspace/ai/skills/feedback-form/session_folder.py`; if it is False, skip
  silently — this is not an error. If True, invoke `victor-skills:feedback-form`
  with the session folder. It clones the previous freeonlinesurveys form,
  retitles it to `derive_form_title(<folder name>)`, publishes it, and POSTs the
  URL to the daemon so participants get it live. When it returns, report the URL
  to the main thread and append to `ai-summary.md`, immediately above the wiki
  footer:

      ## 📝 Feedback

      Two minutes, and it shapes the next session: [<title>](<url>)

  This is a surgical additive edit on the wiki-footer anchor, like every other
  background editor — never a rewrite. If the skill returns an error, report it
  to Victor with the dashboard link and stop; the summary is unaffected.
```

- [ ] **Step 2: Verify the placement**

Run: `grep -n "Feedback form (last day only" ~/workspace/ai/skills/training-summarizer/SKILL.md`
Expected: one hit, inside Step 5's background sub-agent list — **after** the relay hard gate, never before it. Confirm by reading the surrounding lines that the relay + Monitor still come first.

- [ ] **Step 3: Commit and push**

```bash
cd ~/workspace/ai
git add skills/training-summarizer/SKILL.md
git commit -m "feat(training-summarizer): create the feedback form on a session's last day"
git push
```

- [ ] **Step 4: Record the feature in the backlog**

In `training-assistant`, add to `backlog.md`:

```markdown
- [x] direct request (2026-08-13): end-of-session participant feedback form. The `feedback-form` skill clones + retitles + publishes the freeonlinesurveys form via Claude in Chrome on a session's last day, then POSTs the URL to `127.0.0.1:1234/feedback-form`. The daemon persists it to `<session folder>/feedback-form.json` (so it survives the restart every push to master causes), publishes it in session state, and broadcasts `feedback_form_updated`. `static/participant.html` reveals a "Feedback form" left-nav item and a dismissible CTA.
```

```bash
git add backlog.md
git commit -m "docs(backlog): record the end-of-session feedback form automation"
git fetch origin && git rebase origin/master && git push origin master
```

---

## Verification checklist

Before calling this done:

- [ ] `uv run --extra dev --extra daemon --extra telemetry bash tests/check-all.sh` passes.
- [ ] `bash tests/docker/run-hermetic.sh -k feedback_form -m nightly -s` passes **in Docker**.
- [ ] Screenshot of the participant left nav showing "Feedback form", and of the CTA.
- [ ] `curl 127.0.0.1:1234/feedback-form` end-to-end against a live daemon reveals the link on a connected participant without a reload.
- [ ] The link is still there after restarting the daemon.
- [ ] `API.md` and `docs/openapi.yaml` regenerated, never hand-edited.
- [ ] No file under `railway/**` was modified.
