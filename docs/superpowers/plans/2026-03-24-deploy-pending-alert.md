# Deploy Pending Alert — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a push lands on master, GitHub Actions notifies the live server, which broadcasts a blinking "⚠️ Deploy incoming" warning to all connected participant browsers so participants know a restart is imminent.

**Architecture:** The existing `/api/pending-deploy` endpoint in `poll.py` already notifies the host (via state broadcast + `renderPendingDeploy()` in `host.js`). We extend it to also: (1) compare incoming SHA against the server's current `deploy-info.json` to skip duplicate triggers, and (2) broadcast a `deploy_pending` WS message so participants also see a warning. A new GitHub Actions step calls this endpoint on every push to master. No new router file needed.

**Tech Stack:** Python/FastAPI, vanilla JS (no build), GitHub Actions (curl step). Endpoint stays unauthenticated (matches existing `start.sh` usage); SHA comparison guards against abuse.

---

## File Map

| File | Change |
|---|---|
| `routers/poll.py` | **Modify** — add SHA comparison + participant broadcast to `/api/pending-deploy` |
| `.github/workflows/deploy-info.yml` | **Modify** — add `curl` step to notify server on push |
| `static/participant.js` | **Modify** — handle `deploy_pending` WS message → blinking warning |

**No changes to `host.js`** — host already shows deploy warning via `renderPendingDeploy()` / `#pending-deploy-badge`.

---

## Existing infrastructure (read-only, do not break)

- `state.py:96` — `self.pending_deploy: dict | None = None`
- `messaging.py:300` — serializes `pending_deploy` in host state broadcast
- `routers/poll.py:219` — `POST /api/pending-deploy` (no auth) sets `state.pending_deploy` + calls `broadcast_state()`
- `host.js:198` — calls `renderPendingDeploy(msg.pending_deploy)` on every state message
- `host.js:635` — `renderPendingDeploy()` shows/hides `#pending-deploy-badge` with red pulse animation
- `start.sh:110` — local deploy watcher calls `/api/pending-deploy` without auth → must keep working

---

## Task 1: Extend `/api/pending-deploy` with SHA comparison + participant broadcast

**Files:**
- Modify: `routers/poll.py`
- Test: `tests/test_main.py`

### What it does
- Reads current SHA from `static/deploy-info.json` on disk
- If payload `sha` matches current SHA → skip (prevents noise from deploy-info bot commits)
- If different (or sha missing) → existing behavior (`state.pending_deploy = payload; broadcast_state()`) PLUS new: `broadcast({"type": "deploy_pending"})`
- `start.sh` calls this with `{"sha": "abc12345", "message": "feat: ..."}` — still works (sha is short 8-char prefix which will never match the full sha in deploy-info.json → always broadcasts; this is intentional, start.sh is on the trainer's Mac and its notifications are legitimate)

### Current code at `routers/poll.py:219-224`
```python
@router.post("/api/pending-deploy")
async def set_pending_deploy(payload: dict):
    """Called by deploy watcher when a new push is detected on master."""
    state.pending_deploy = payload if payload.get("sha") else None
    await broadcast_state()
    return {"status": "ok"}
```

### Updated code
```python
@router.post("/api/pending-deploy")
async def set_pending_deploy(payload: dict):
    """Called by deploy watcher or GitHub Actions when a new push is detected on master."""
    incoming_sha = (payload.get("sha") or "").strip()
    current_sha = _read_deploy_sha()
    if incoming_sha and current_sha and incoming_sha == current_sha:
        logger.info("pending-deploy: same SHA %s — skipping", incoming_sha[:8])
        return {"status": "ok", "action": "ignored"}
    state.pending_deploy = payload if incoming_sha else None
    await broadcast_state()
    if incoming_sha:
        await broadcast({"type": "deploy_pending"})
    return {"status": "ok", "action": "broadcast"}
```

Add helper (add near top of file, after imports):
```python
import json as _json
from pathlib import Path as _Path

_DEPLOY_INFO = _Path(__file__).parent.parent / "static" / "deploy-info.json"

def _read_deploy_sha() -> str:
    try:
        return str(_json.loads(_DEPLOY_INFO.read_text(encoding="utf-8")).get("sha", ""))
    except Exception:
        return ""
```

Add import at top of `poll.py` (with existing imports):
```python
from messaging import broadcast
```

Add logger near top of `poll.py`:
```python
import logging
logger = logging.getLogger(__name__)
```

(Check if `broadcast` and `logger` are already imported in `poll.py` before adding — avoid duplicates.)

- [ ] **Step 1: Read current `routers/poll.py` imports and top-of-file section**

```bash
head -30 routers/poll.py
```

Note what is already imported to avoid duplicates in Step 3.

- [ ] **Step 2: Write the failing test**

Add to `tests/test_main.py`:

```python
def test_pending_deploy_broadcasts_to_participants(monkeypatch):
    """POST /api/pending-deploy with a new SHA broadcasts deploy_pending WS message."""
    import json
    from pathlib import Path
    deploy_info = Path(__file__).parent.parent / "static" / "deploy-info.json"
    original = deploy_info.read_text() if deploy_info.exists() else None
    try:
        deploy_info.write_text(json.dumps({"sha": "aaa111bbb222ccc333", "timestamp": "x", "changelog": []}))

        broadcast_calls = []
        async def fake_broadcast(msg, exclude=None):
            broadcast_calls.append(msg)
        monkeypatch.setattr("routers.poll.broadcast", fake_broadcast)

        client = TestClient(app)
        response = client.post("/api/pending-deploy",
                               json={"sha": "ddd444eee555fff666", "message": "feat: new thing"})
        assert response.status_code == 200
        assert any(c.get("type") == "deploy_pending" for c in broadcast_calls)
    finally:
        if original is not None:
            deploy_info.write_text(original)


def test_pending_deploy_same_sha_no_broadcast(monkeypatch):
    """POST /api/pending-deploy with same full SHA does NOT broadcast deploy_pending."""
    import json
    from pathlib import Path
    deploy_info = Path(__file__).parent.parent / "static" / "deploy-info.json"
    original = deploy_info.read_text() if deploy_info.exists() else None
    try:
        deploy_info.write_text(json.dumps({"sha": "aaa111bbb222ccc333", "timestamp": "x", "changelog": []}))

        broadcast_calls = []
        async def fake_broadcast(msg, exclude=None):
            broadcast_calls.append(msg)
        monkeypatch.setattr("routers.poll.broadcast", fake_broadcast)

        client = TestClient(app)
        response = client.post("/api/pending-deploy",
                               json={"sha": "aaa111bbb222ccc333", "message": "same commit"})
        assert response.status_code == 200
        assert not any(c.get("type") == "deploy_pending" for c in broadcast_calls)
    finally:
        if original is not None:
            deploy_info.write_text(original)
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd /Users/victorrentea/conductor/workspaces/training-assistant/macau
pytest tests/test_main.py -k "pending_deploy" -v
```
Expected: FAIL — `AssertionError` (broadcast not called yet)

- [ ] **Step 4: Implement changes in `routers/poll.py`**

Add `_DEPLOY_INFO`, `_read_deploy_sha()`, and update `set_pending_deploy()` as shown above.
Add `import logging; logger = logging.getLogger(__name__)` and `from messaging import broadcast` if not already present.

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_main.py -k "pending_deploy" -v
```
Expected: 2 new tests PASS, all other existing tests still PASS.

Also run full suite:
```bash
pytest tests/test_main.py -v
```
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add routers/poll.py tests/test_main.py
git commit -m "feat(deploy): broadcast deploy_pending to participants + SHA dedup guard"
```

---

## Task 2: GitHub Actions — notify server on push

**Files:**
- Modify: `.github/workflows/deploy-info.yml`

### What it does
Adds a step after "Commit and push" that calls the live server with `$GITHUB_SHA` (the original push commit, always available as a GitHub Actions env var). No auth needed — endpoint is public. Silently continues on failure.

`$GITHUB_SHA` is the commit that triggered the workflow (before any deploy-info bot commit). It will never equal the server's current `deploy-info.json` SHA → always triggers the warning. This is correct: any human push means a deploy is coming.

**No GitHub secrets needed** — endpoint is public.

- [ ] **Step 1: Add notify step to `deploy-info.yml`**

Append after the "Commit and push" step:

```yaml
      - name: Notify server of incoming deploy
        env:
          SERVER_URL: https://interact.victorrentea.ro
        run: |
          curl -sf -X POST "$SERVER_URL/api/pending-deploy" \
            -H "Content-Type: application/json" \
            -d "{\"sha\": \"$GITHUB_SHA\", \"message\": \"CI push\"}" \
            --max-time 10 \
          || echo "Server notify failed (non-fatal)"
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/deploy-info.yml
git commit -m "feat(deploy): notify server on push via GitHub Actions"
```

---

## Task 3: Frontend — blinking "Deploy incoming" warning in participant.js

**Files:**
- Modify: `static/participant.js`

### What it does
When a `deploy_pending` WS message arrives in participant.js:
1. Finds `#version-tag` element (top-right corner, currently shows deploy age)
2. Replaces its content with `⚠️ Deploy incoming`
3. Applies blinking orange style via injected CSS keyframes

The blinking stops naturally when the page reloads (triggered by `version-reload.js` once the new version is live — it detects version change and shows a "Reload now" banner).

**Host is NOT touched** — `host.js` already handles this via `renderPendingDeploy()` / `#pending-deploy-badge`.

- [ ] **Step 1: Add `showDeployPending()` and `deploy_pending` handler in `participant.js`**

Find the `handleMessage` switch block (around line 640). Add a new `case` after the last existing case:

```javascript
case 'deploy_pending':
  showDeployPending();
  break;
```

Add `showDeployPending()` function near other UI helpers (search for `function notifyIfHidden` as a landmark — add after it):

```javascript
function showDeployPending() {
  const el = document.getElementById('version-tag');
  if (!el) return;
  if (!document.getElementById('_blink-style')) {
    const s = document.createElement('style');
    s.id = '_blink-style';
    s.textContent = '@keyframes _blink-warning{0%,100%{opacity:1}50%{opacity:.25}}';
    document.head.appendChild(s);
  }
  el.textContent = '⚠️ Deploy incoming';
  el.style.cssText = 'color:#f5a623;opacity:1;animation:_blink-warning 1s ease-in-out infinite;font-weight:600;';
}
```

- [ ] **Step 2: Manual smoke test**

Start server locally:
```bash
python3 -m uvicorn main:app --reload --port 8000
```

Open http://localhost:8000 (participant tab).

Trigger:
```bash
curl -X POST http://localhost:8000/api/pending-deploy \
  -H "Content-Type: application/json" \
  -d '{"sha": "totally-different-sha-xyz", "message": "test deploy"}'
```

Expected: Participant tab shows `⚠️ Deploy incoming` blinking orange in top-right corner.

Test same SHA (no blink):
```bash
SHA=$(python3 -c "import json; print(json.load(open('static/deploy-info.json'))['sha'])")
curl -X POST http://localhost:8000/api/pending-deploy \
  -H "Content-Type: application/json" \
  -d "{\"sha\": \"$SHA\", \"message\": \"same\"}"
```
Expected: No change in browser.

- [ ] **Step 3: Commit**

```bash
git add static/participant.js
git commit -m "feat(deploy): show blinking deploy-pending warning for participants"
```

---

## Task 4: Merge to master and verify end-to-end

- [ ] **Step 1: Fetch and rebase**

```bash
git fetch origin
git rebase origin/master
```

- [ ] **Step 2: Run full test suite**

```bash
pytest tests/test_main.py -v
```
Expected: all green.

- [ ] **Step 3: Push to master**

```bash
git checkout master
git merge victorrentea/deploy-pending-alert
git push origin master
```

- [ ] **Step 4: Watch GitHub Actions**

Go to repo Actions tab. Verify `deploy-info` job → "Notify server" step exits 0.

- [ ] **Step 5: Verify on production**

While Railway deploys (~40-50s), open https://interact.victorrentea.ro.
Confirm ⚠️ Deploy incoming blinks orange in top-right.
After deploy, confirm `version-reload.js` banner appears and blink stops after reload.
