# Participant Tab URL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the participant view's address bar always reflect the active tab (`/<session>/notes`, `/<session>/files`, `/<session>/slides`, `/<session>/activity`, `/<session>/summary`, `/<session>/agenda`, `/<session>/upload-paste`, `/<session>/past-slides`) so a tab-specific link can be pasted and shared.

**Architecture:** Backend adds a single-segment `/{session_id}/{tab}` route that serves the participant SPA for known tab slugs (and relocates the existing standalone read-only notes page from `/notes` to `/notes-print`). The SPA writes the URL via `history.replaceState` from its single `showView` chokepoint (plus the slide picker and the Past Slides toggle), and reads a tab slug from the URL on load to override the last-used tab.

**Tech Stack:** FastAPI (Railway backend, Python), vanilla JS (no build step), pytest + Starlette `TestClient` (backend), Playwright in Docker (hermetic E2E).

**Spec:** `docs/superpowers/specs/2026-06-10-participant-tab-url-design.md`

**Note on commands:** Work happens in a git worktree. Run pytest via `uv` so deps resolve. On Apple Silicon prefer the hook-parity form `arch -arm64 uv run --extra dev --extra daemon --extra telemetry ...`. Examples below use `uv run --extra dev --extra daemon --extra telemetry pytest ...`; drop the prefix if the environment is already provisioned.

---

## File Structure

- **Modify** `railway/features/pages/router.py` — extract `_serve_participant_app()`, relocate `/notes` → `/notes-print`, add `/{tab}` with a slug allowlist. Single responsibility: HTML page routing.
- **Create** `tests/features/pages/__init__.py` and `tests/features/pages/test_router.py` — backend route contract tests (mirrors `tests/features/slides/test_router.py`).
- **Modify** `openapi.json`, `API.md` — regenerated artifacts (never hand-edited).
- **Modify** `static/participant.html` — `_setTabUrl` helper + wiring + init deep-link parse. (Large existing single file; follow its existing inline-JS style, do not restructure.)
- **Create** `tests/docker/test_participant_tab_url.py` — hermetic Playwright E2E.
- **Modify** `backlog.md` — record the change.

---

## Task 1: Backend routing — relocate notes page + add tab route

**Files:**
- Create: `tests/features/pages/__init__.py`
- Create: `tests/features/pages/test_router.py`
- Modify: `railway/features/pages/router.py`

- [ ] **Step 1: Create the test package init**

Create `tests/features/pages/__init__.py` as an empty file:

```python
```

- [ ] **Step 2: Write the failing tests**

Create `tests/features/pages/test_router.py`:

```python
"""Contract tests for participant HTML page routing (tabs + relocated notes page)."""

from fastapi.testclient import TestClient

from railway.app import app, state

# A marker unique to the participant SPA (present in static/participant.html,
# absent from the standalone static/notes.html).
_APP_MARKER = b'data-nav="activity"'


def setup_function():
    state.reset()
    state.session_id = "e2etst"


def teardown_function():
    state.reset()


def test_root_serves_participant_app():
    client = TestClient(app)
    resp = client.get(f"/{state.session_id}/")
    assert resp.status_code == 200
    assert _APP_MARKER in resp.content


def test_tab_slug_serves_participant_app():
    client = TestClient(app)
    for tab in ("notes", "files", "slides", "activity", "summary",
                "agenda", "upload-paste", "feedback", "past-slides"):
        resp = client.get(f"/{state.session_id}/{tab}")
        assert resp.status_code == 200, tab
        assert _APP_MARKER in resp.content, tab


def test_notes_print_serves_readonly_page():
    client = TestClient(app)
    resp = client.get(f"/{state.session_id}/notes-print")
    assert resp.status_code == 200
    assert b"Session Notes" in resp.content
    assert _APP_MARKER not in resp.content  # not the SPA


def test_unknown_tab_is_404():
    client = TestClient(app)
    resp = client.get(f"/{state.session_id}/totally-bogus")
    assert resp.status_code == 404
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run --extra dev --extra daemon --extra telemetry pytest tests/features/pages/test_router.py -v`
Expected: `test_tab_slug_serves_participant_app` FAILS (404 for `/files` etc.), `test_notes_print_serves_readonly_page` FAILS (404 — route doesn't exist yet). `test_root_serves_participant_app` should already PASS.

- [ ] **Step 4: Implement the route changes**

Edit `railway/features/pages/router.py`. Change the import line:

```python
from fastapi import APIRouter, Depends, HTTPException
```

Replace the existing `participant_page` and `notes_page` definitions (the block starting at `@participant_router.get("/", ...)` through the end of `notes_page`) with:

```python
# Valid participant SPA tab slugs that may appear as the path segment after the
# session id (mirrors the VIEWS array in static/participant.html, plus the
# past-slides panel). Unknown slugs 404 so the catch-all cannot swallow garbage.
_PARTICIPANT_TAB_SLUGS = frozenset(
    {
        "slides",
        "activity",
        "summary",
        "notes",
        "agenda",
        "feedback",
        "upload-paste",
        "files",
        "past-slides",
    }
)


def _serve_participant_app() -> HTMLResponse | FileResponse:
    """Serve the participant SPA (talk variant for talk sessions)."""
    if state.session_type == "talk":
        return _serve_html_with_otel("static/talk.html", service_name="Talk")
    return _serve_html_with_otel("static/participant.html", service_name="Participant")


@participant_router.get("/", response_class=HTMLResponse)
async def participant_page():
    return _serve_participant_app()


@participant_router.get("/notes-print", response_class=HTMLResponse)
async def notes_print_page():
    """Standalone read-only session notes page (formerly served at /<session>/notes)."""
    return FileResponse("static/notes.html")


@participant_router.get("/{tab}", response_class=HTMLResponse)
async def participant_tab_page(tab: str):
    """Serve the participant SPA for a deep-linked tab (e.g. /<session>/notes)."""
    if tab not in _PARTICIPANT_TAB_SLUGS:
        raise HTTPException(status_code=404, detail="Unknown tab")
    return _serve_participant_app()
```

Route order in the file MUST be `/`, then `/notes-print`, then `/{tab}` (literal routes are matched before the path param).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --extra dev --extra daemon --extra telemetry pytest tests/features/pages/test_router.py -v`
Expected: all 4 PASS.

- [ ] **Step 6: Commit**

```bash
git add railway/features/pages/router.py tests/features/pages/__init__.py tests/features/pages/test_router.py
git commit -m "feat(routing): serve participant SPA per tab; relocate notes page to /notes-print"
```

---

## Task 2: Regenerate the OpenAPI contract + API.md

The page routes appear in `openapi.json`, which is snapshot-tested by `tests/openapi/test_contract.py`. Adding `/{tab}` and renaming `/notes` → `/notes-print` changes the contract, so regenerate the committed artifacts.

**Files:**
- Modify: `openapi.json`
- Modify: `API.md`

- [ ] **Step 1: Confirm the contract test currently fails**

Run: `uv run --extra dev --extra daemon --extra telemetry pytest tests/openapi/test_contract.py -v`
Expected: FAIL — committed `openapi.json` no longer matches `app.openapi()`.

- [ ] **Step 2: Regenerate openapi.json**

Run:
```bash
uv run --extra dev --extra daemon --extra telemetry python3 -c "from railway.app import app; import json; print(json.dumps(app.openapi(), indent=2))" > openapi.json
```

- [ ] **Step 3: Regenerate API.md**

Run:
```bash
uv run --extra dev --extra daemon --extra telemetry python3 scripts/generate_apis_md.py --output API.md
```

- [ ] **Step 4: Verify both contract/docs tests pass**

Run: `uv run --extra dev --extra daemon --extra telemetry pytest tests/openapi/test_contract.py tests/docs/test_generate_apis_md.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add openapi.json API.md
git commit -m "chore(api): regenerate openapi.json + API.md for tab routes"
```

---

## Task 3: Frontend — `_setTabUrl` helper + wire into view switches

No JS unit-test harness exists in this repo; the verification for Tasks 3–4 is the hermetic E2E in Task 5 (plus an optional local browser smoke). Keep each edit small and follow the file's existing inline style.

**Files:**
- Modify: `static/participant.html` (helper before `showView` at ~line 2167; inside `showView`; inside `selectTopic` at ~line 2050; inside `togglePastSlides` at ~line 1574)

- [ ] **Step 1: Add the `_setTabUrl` helper just before `function showView(name) {`**

Insert immediately above the `function showView(name) {` line:

```javascript
// Reflect the active tab in the address bar so a tab-specific link can be shared.
// replaceState (not pushState): switching tabs must not stack browser history
// entries or turn the mobile back-gesture into "undo tab change".
function _setTabUrl(slug) {
  if (!_sessionId || !slug) return;
  var path = '/' + _sessionId + '/' + slug;
  if (location.pathname !== path) {
    try { history.replaceState(null, '', path); } catch (e) {}
  }
}
```

- [ ] **Step 2: Call it from `showView`**

In `function showView(name)`, find the line `LS.setView(name);` and add `_setTabUrl(name);` right after it:

```javascript
  LS.setView(name);
  _setTabUrl(name);
```

- [ ] **Step 3: Call it from `selectTopic` (slide pick implies the slides tab)**

In `async function selectTopic(...)`, find the existing block that shows the slides view:

```javascript
  VIEWS.forEach(function(v) {
    document.getElementById(v + '-view').style.display = v === 'slides' ? '' : 'none';
  });
```

Add immediately after that block:

```javascript
  _setTabUrl('slides');
```

- [ ] **Step 4: Wire `togglePastSlides` to set/revert the URL**

Replace the body of `function togglePastSlides()`:

```javascript
function togglePastSlides() {
  var el = document.getElementById('slide-history-list');
  var isOpen = !!(el && el.style.display !== 'none');
  if (!isOpen) {
    openPastSlides();
    _setTabUrl('past-slides');
  } else {
    closePastSlides({ focusAllTopics: false });
    _setTabUrl(LS.getView());
  }
}
```

- [ ] **Step 5: Syntax sanity check**

Run: `node --check static/participant.html 2>&1 | head` is NOT valid (it's HTML). Instead extract-and-check is overkill; do a quick visual diff:
Run: `git diff static/participant.html`
Expected: only the four small additions above; balanced braces; no stray edits.

- [ ] **Step 6: Commit**

```bash
git add static/participant.html
git commit -m "feat(participant): write active tab to the URL via replaceState"
```

---

## Task 4: Frontend — read the tab slug from the URL on load

**Files:**
- Modify: `static/participant.html` (init block at ~line 2911, inside the state-loading IIFE)

- [ ] **Step 1: Override the starting view from the URL**

Find this block (just before `_hostSlidesCurrent = state.slides_current || null;`):

```javascript
    var saved = LS.getView();
    if (saved === 'agenda' && !state.has_agenda) saved = 'slides';
    if (saved === 'notes' && !state.notes_updated_at) saved = 'slides';
    if (saved === 'summary' && !state.summary_updated_at) saved = 'slides';
    _hostSlidesCurrent = state.slides_current || null;
    showView(saved);
```

Replace it with:

```javascript
    var saved = LS.getView();
    // A tab slug in the URL (e.g. /<session>/notes) overrides the last-used tab,
    // so a shared deep link opens on the intended tab.
    var urlTab = (location.pathname.split('/')[2] || '').toLowerCase();
    if (VIEWS.indexOf(urlTab) !== -1 || urlTab === 'past-slides') saved = urlTab;
    if (saved === 'agenda' && !state.has_agenda) saved = 'slides';
    if (saved === 'notes' && !state.notes_updated_at) saved = 'slides';
    if (saved === 'summary' && !state.summary_updated_at) saved = 'slides';
    _hostSlidesCurrent = state.slides_current || null;
    if (saved === 'past-slides') {
      showView('slides');
      openPastSlides();
      _setTabUrl('past-slides');
    } else {
      showView(saved);
    }
```

- [ ] **Step 2: Visual diff check**

Run: `git diff static/participant.html`
Expected: only the init block changed as above; `VIEWS`, `openPastSlides`, and `_setTabUrl` are all referenced and defined elsewhere in the file.

- [ ] **Step 3: (Optional) local browser smoke**

If a daemon + active session is available locally (host page at `http://localhost:8081/`): open `http://localhost:8081/<session>/files`, confirm the Files tab is shown and the bar reads `/<session>/files`; click another tab and confirm the bar updates. (Full proof is the Docker E2E in Task 5.)

- [ ] **Step 4: Commit**

```bash
git add static/participant.html
git commit -m "feat(participant): open the tab named in the URL on load"
```

---

## Task 5: Hermetic E2E — deep-link + URL rewrite + notes-print

**Files:**
- Create: `tests/docker/test_participant_tab_url.py`

- [ ] **Step 1: Write the E2E test**

Create `tests/docker/test_participant_tab_url.py`:

```python
"""Hermetic E2E: the participant URL reflects the active tab.

- Deep-link /<session>/files lands on the Files tab.
- Clicking the Activity nav rewrites the address bar to /<session>/activity.
- The standalone read-only notes page lives at /<session>/notes-print.
"""

import sys

import pytest

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

from pages.participant_page import ParticipantPage
from playwright.sync_api import expect, sync_playwright
from session_utils import fresh_session

pytestmark = pytest.mark.nightly

BASE = "http://localhost:8000"


def test_tab_url_deeplink_and_rewrite():
    session_id = fresh_session("TabUrl")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        # Deep-link directly to the (ungated) Files tab.
        page.goto(f"{BASE}/{session_id}/files", wait_until="networkidle")
        ParticipantPage(page).auto_join()
        expect(page.locator("#files-view")).to_be_visible(timeout=10000)
        expect(page.locator("#slides-view")).to_be_hidden()
        # Switching tabs rewrites the address bar.
        page.locator('[data-nav="activity"]').click()
        expect(page.locator("#activity-view")).to_be_visible(timeout=10000)
        page.wait_for_url(f"{BASE}/{session_id}/activity", timeout=5000)
        assert page.url.endswith(f"/{session_id}/activity")
        browser.close()


def test_notes_print_page_served():
    session_id = fresh_session("NotesPrint")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"{BASE}/{session_id}/notes-print", wait_until="networkidle")
        expect(page.locator("text=Session Notes")).to_be_visible(timeout=10000)
        browser.close()
```

- [ ] **Step 2: Build + run the hermetic test in Docker**

Run: `bash tests/docker/run-hermetic.sh -k test_participant_tab_url -m nightly -s`
Expected: both tests PASS. (Hermetic tests are nightly-tagged and must run in Docker — never claim done without this run.)

- [ ] **Step 3: Capture proof**

In the run output, confirm the URL-rewrite assertion (`page.url.endswith('/activity')`) passed. If a screenshot is desired, add `page.screenshot(path="/app/pax-tab-url.png")` before `browser.close()` in the first test and re-run; otherwise the assertion log is sufficient proof for this non-visual behavior.

- [ ] **Step 4: Commit**

```bash
git add tests/docker/test_participant_tab_url.py
git commit -m "test(e2e): participant tab deep-link + URL rewrite + notes-print"
```

---

## Task 6: Audit old `/notes` references + backlog entry

**Files:**
- Modify (only if matches found): any file linking to the old standalone notes URL
- Modify: `backlog.md`

- [ ] **Step 1: Grep for links to the old standalone notes page**

Run:
```bash
grep -rnE "/notes['\"\\\`) ]|\\}/notes\\b|sessionId.*/notes|session_id.*/notes" static/ railway/ daemon/ docs/ --include='*.html' --include='*.js' --include='*.py' --include='*.md' | grep -vE "notes-view|notes-scroll|notes-content|notes-badge|notes-print|/api/.*notes|data-nav=.notes|loadNotes|notes_updated|#notes|_notes|notesDirty|saveScroll|notes-md|\.txt"
```
Expected: no matches. If any user-facing link to `/<session>/notes` (the read-only page) is found, update it to `/<session>/notes-print`. Re-run Task 1's backend tests if a source file changed.

- [ ] **Step 2: Add a backlog entry**

Append to `backlog.md` (match the file's existing format) a concise entry:

```markdown
- Participant URL now reflects the active tab (`/<session>/<tab>`), enabling shareable tab-deep-links; the standalone read-only notes page moved from `/<session>/notes` to `/<session>/notes-print`.
```

- [ ] **Step 3: Commit**

```bash
git add backlog.md
git commit -m "docs(backlog): participant tab-aware URLs + notes-print relocation"
```

---

## Task 7: Full verification + ship

- [ ] **Step 1: Run the full quick suite**

Run: `arch -arm64 uv run --extra dev --extra daemon --extra telemetry bash tests/check-all.sh`
Expected: PASS (this reproduces the `hooks/pre-push` gate). Fix any failures before proceeding.

- [ ] **Step 2: Merge the worktree branch into master and push**

From the worktree, integrate to `master` (fetch + rebase first per project rules), then push:
```bash
git fetch origin master
git rebase origin/master    # resolve any conflicts
```
Then fast-forward `master` to this branch and push (or open per the project's merge convention — project rule is push directly to master):
```bash
git checkout master && git merge --ff-only worktree-participant-tab-url && git push origin master
```
Expected: push accepted.

- [ ] **Step 3: Verify live in production**

After the Railway deploy (~40–50s), confirm the change took effect:
```bash
# Replace <s> with the active session id.
curl -s -o /dev/null -w "%{http_code}\n" https://interact.victorrentea.ro/<s>/files       # expect 200 (SPA)
curl -s https://interact.victorrentea.ro/<s>/notes-print | grep -o "Session Notes" | head  # expect match
curl -s -o /dev/null -w "%{http_code}\n" https://interact.victorrentea.ro/<s>/totally-bogus # expect 404
```
Expected: SPA served for tab slugs, read-only page at `/notes-print`, 404 for unknown slugs. Do not declare done until prod confirms.

---

## Self-Review

**Spec coverage:**
- Path-based URLs, app takes over `/notes`, standalone relocated → Task 1. ✓
- All tabs reflected (VIEWS + past-slides) → slug set in Task 1; `showView` wiring in Task 3; init parse in Task 4. ✓
- `replaceState` semantics → Task 3 Step 1. ✓
- Deep-link overrides localStorage; availability fallbacks preserved; past-slides special-case → Task 4. ✓
- Bare `/` rewrites to `/slides` → consequence of Task 3 Step 2 + Task 4 (documented). ✓
- Backend route matrix (`notes`, `notes-print`, tabs, garbage→404) → Task 1 tests. ✓
- OpenAPI/API.md regen → Task 2. ✓
- Hermetic E2E proof → Task 5. ✓
- Audit old `/notes` links → Task 6. ✓
- check-all + prod verification → Task 7. ✓

**Placeholder scan:** No TBD/TODO; every code step shows the full code; every command shows expected output. ✓

**Type/name consistency:** `_setTabUrl`, `_serve_participant_app`, `_PARTICIPANT_TAB_SLUGS`, `_APP_MARKER`, and slug strings are used identically across tasks; slug set matches `VIEWS` ∪ {`past-slides`}. ✓
