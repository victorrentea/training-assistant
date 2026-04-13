# Participant Join Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the participant join/landing flow per the activity diagram in `docs/participant-join-activity.puml` — multi-screen landing page with session validation, name entry, rejoin, and host auto-join.

**Architecture:** The landing page (`static/landing.html`) becomes a multi-screen SPA handling the full join flow: is-active-session check → session code entry → name entry / rejoin → navigate to participant app (`/{session_id}`). A new Railway endpoint `GET /api/is-active-session` returns a simple boolean. The existing `POST /{session_id}/api/participant/register` remains the registration mechanism. On WS disconnect, `participant.js` redirects to `/?session_id=X` instead of `/?code=X&retry=1`.

**Tech Stack:** Vanilla JS (no framework), FastAPI, Playwright (hermetic e2e tests)

**Spec:** `docs/participant-join-activity.puml` (the activity diagram)

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `railway/app.py` | Add `GET /api/is-active-session` endpoint |
| Rewrite | `static/landing.html` | Multi-screen join flow (is-active → code entry → name entry → enter app) |
| Modify | `static/participant.js` | Change WS disconnect redirect to `/?session_id=X`; accept name from URL/localStorage |
| Create | `tests/docker/test_participant_join_flow.py` | Hermetic e2e tests for all diagram branches |

---

### Task 1: Add `GET /api/is-active-session` Railway endpoint

**Files:**
- Modify: `railway/app.py:160-163`
- Test: `tests/daemon/test_host_state_router.py` (quick unit test)

- [ ] **Step 1: Write the endpoint**

In `railway/app.py`, add the new endpoint after the existing `/api/session/active`:

```python
@app.get("/api/is-active-session")
async def is_active_session():
    """Public endpoint: returns whether any session is currently active (boolean only, no session_id)."""
    return {"active": state.session_id is not None}
```

- [ ] **Step 2: Verify manually**

```bash
curl http://localhost:8000/api/is-active-session
# Expected: {"active":false} (no daemon connected)
```

- [ ] **Step 3: Commit**

```bash
git add railway/app.py
git commit -m "feat: add GET /api/is-active-session public endpoint"
```

---

### Task 2: Rewrite `static/landing.html` — multi-screen join flow

**Files:**
- Rewrite: `static/landing.html`

This is the core task. The landing page becomes a multi-screen flow with these states:

1. **Screen: checking** — "Connecting..." spinner while calling `/api/is-active-session`
2. **Screen: error-no-host** — "Host not connected" (request failed)
3. **Screen: error-no-session** — "No session started" (response = false)
4. **Screen: code-entry** — 6-digit session code input (Case A, no `?session_id`)
5. **Screen: session-mismatch** — "Session not started" with link to clear session_id (Case B)
6. **Screen: name-entry** — Session code (read-only) + name input + "Random name" button
7. **Screen: entering** — Brief "Joining..." while registering

The host flow is handled transparently: `pollLocalDaemon()` detects `localhost:1234`, fetches session_id from daemon, sets the query param, and the normal flow handles the rest.

- [ ] **Step 1: Write the complete landing.html**

Key behaviors to implement per diagram:

**is-active-session check (top of flow):**
- On page load, call `GET /api/is-active-session`
- 3-way response: request failed → "Host not connected"; `{active:false}` → "No session started"; `{active:true}` → continue
- **Participant retry:** 5 attempts with backoff delays [1s, 2s, 3s, 5s, 5s], then stop
- **Host retry:** poll every 3s indefinitely (detected via `pollLocalDaemon` trying `localhost:1234`)
- Both error screens show a "Retrying in Xs..." countdown

**ON_HOST_MACHINE (before code entry):**
- `pollLocalDaemon()` polls `GET localhost:1234/api/session/active` every 1s
- On success: set `?session_id={id}` in URL and proceed (existing behavior, just adapted to query param)

**Case A — no session_id query param:**
- Show code-entry screen: input for 6-digit session code
- Auto-submit when 6 chars entered
- Validate via `GET /{code}/api/status` — 200 means valid, 404 means invalid
- On valid: redirect to `?session_id={code}` (page reloads with param)
- On invalid: shake input, red font, toaster "Invalid session code"

**Case B — session_id doesn't match active:**
- After redirect with `?session_id=X`, check via `GET /{session_id}/api/status`
- If 404: show "Session not started" screen
- Show gray link: "click here to enter another session id" → navigates to `/` (clears param)

**Case C — session_id matches active:**
- Check session type via `GET /{session_id}/api/status` response
- If conference: show error "NOT SUPPORTED YET"
- If workshop: proceed to UUID/rejoin check

**UUID and rejoin:**
- Check localStorage for `workshop_participant_uuid`
- If UUID exists: attempt `POST /{session_id}/api/participant/register` with `X-Participant-ID` header
  - If response has a name (idempotent return for existing participant): ENTER the app
  - If new registration: fall through to name entry
- If no UUID: generate with `crypto.randomUUID()`, store in localStorage

**ON_HOST_MACHINE registration:**
- If `is_host=1` cookie detected: call `POST /{session_id}/api/participant/register` (gets random LOTR name)
- Append " (host)" to received name
- Store name in sessionStorage (not localStorage, for multi-tab)
- ENTER the app immediately

**Name entry screen (participants only):**
- Show session_id (read-only) in input above name input
- Show name input + "Random name" button
- "Random name": call `POST /{session_id}/api/participant/register` → gets auto-assigned LOTR name → ENTER app
- "Submit name": call `POST /{session_id}/api/participant/register` then `PUT /{session_id}/api/participant/name` with custom name
  - 409 from PUT → shake input, toaster "Name taken"
  - 204 from PUT → ENTER the app
- Button disabled when input is empty/whitespace-only (per CLAUDE.md rule)

**ENTER the app:**
- `window.location.href = '/' + sessionId`
- This navigates to `/{session_id}` which loads `participant.html`
- Store the assigned/chosen name in localStorage so `participant.js` can use it

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Join Session - Interact</title>
  <link rel="icon" type="image/svg+xml" href="/static/favicon-participant.svg" />
  <link rel="stylesheet" href="/static/common.css" />
  <style>
    body {
      background: var(--bg);
      color: var(--text);
      font-family: 'Segoe UI', system-ui, sans-serif;
      min-height: 100vh;
      margin: 0;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .landing-card {
      text-align: center;
      padding: 2.5rem 2rem;
      max-width: 380px;
      width: 100%;
    }
    .landing-logo {
      font-size: 2.2rem;
      font-weight: 800;
      margin-bottom: .3rem;
      color: var(--accent);
    }
    .screen { display: none; }
    .screen.active { display: block; }

    .landing-input {
      width: 100%;
      max-width: 260px;
      background: var(--surface2);
      color: var(--text);
      border: 2px solid var(--border);
      border-radius: var(--radius);
      padding: .85rem 1rem;
      font-size: 1.4rem;
      font-weight: 700;
      text-align: center;
      letter-spacing: .25em;
      text-transform: uppercase;
      box-sizing: border-box;
      outline: none;
      transition: border-color .15s;
    }
    .landing-input:focus { border-color: var(--accent); }
    .landing-input::placeholder {
      font-weight: 400; letter-spacing: .05em; text-transform: none;
      font-size: 1rem; color: var(--muted); opacity: .7;
    }
    .landing-input.readonly {
      opacity: .6;
      font-size: 1rem;
      letter-spacing: .15em;
      cursor: default;
      margin-bottom: .8rem;
    }

    .name-input {
      font-size: 1.1rem;
      font-weight: 600;
      letter-spacing: .02em;
      text-transform: none;
    }

    .landing-btn {
      display: block;
      width: 100%;
      max-width: 260px;
      margin: 1rem auto 0;
      padding: .8rem 1.2rem;
      background: var(--accent);
      color: #fff;
      border: none;
      border-radius: var(--radius);
      font-size: 1.1rem;
      font-weight: 700;
      cursor: pointer;
      transition: filter .15s, transform .1s;
    }
    .landing-btn:hover:not(:disabled) { filter: brightness(1.25); }
    .landing-btn:active:not(:disabled) { transform: scale(.97); }
    .landing-btn:disabled { opacity: .35; cursor: default; }
    .landing-btn.secondary {
      background: transparent;
      color: var(--muted);
      font-size: .85rem;
      font-weight: 400;
      margin-top: .5rem;
      text-decoration: underline;
    }

    .landing-error {
      color: var(--danger);
      font-size: .85rem;
      font-weight: 600;
      margin-top: .8rem;
      min-height: 1.2em;
    }
    .landing-status {
      color: var(--muted);
      font-size: .85rem;
      margin-top: 1rem;
      min-height: 1.2em;
    }
    .status-icon { font-size: 2.5rem; margin-bottom: 1rem; }
    .gray-link {
      color: var(--muted);
      font-size: .8rem;
      margin-top: 1.2rem;
      display: inline-block;
      cursor: pointer;
      text-decoration: underline;
    }
    .gray-link:hover { color: var(--text); }

    @keyframes shake {
      0%, 100% { transform: translateX(0); }
      20%, 60% { transform: translateX(-6px); }
      40%, 80% { transform: translateX(6px); }
    }
    .shake { animation: shake .4s ease; }

    /* Toast notification */
    .toast {
      position: fixed;
      top: 1.5rem;
      left: 50%;
      transform: translateX(-50%);
      background: var(--danger);
      color: #fff;
      padding: .6rem 1.5rem;
      border-radius: var(--radius);
      font-weight: 600;
      font-size: .9rem;
      z-index: 9999;
      opacity: 0;
      transition: opacity .3s;
      pointer-events: none;
    }
    .toast.show { opacity: 1; }
  </style>
</head>
<body>
  <div class="landing-card">
    <div class="landing-logo">Join a Session</div>

    <!-- Screen: checking -->
    <div id="screen-checking" class="screen active">
      <div class="landing-status">Connecting...</div>
    </div>

    <!-- Screen: error (host not connected / no session) -->
    <div id="screen-error" class="screen">
      <div class="status-icon" id="error-icon"></div>
      <div id="error-title" style="font-size:1.1rem;font-weight:700;margin-bottom:.5rem;"></div>
      <div id="error-retry-status" class="landing-status"></div>
    </div>

    <!-- Screen: code entry (Case A) -->
    <div id="screen-code" class="screen">
      <label style="font-size:1rem;font-weight:600;margin-bottom:.7rem;display:block;" for="code-input">
        Enter session code
      </label>
      <input
        id="code-input"
        class="landing-input"
        type="text"
        maxlength="6"
        autocomplete="off"
        autocapitalize="none"
        spellcheck="false"
        placeholder="e.g. k7m2xp"
      />
      <div id="code-error" class="landing-error"></div>
    </div>

    <!-- Screen: session mismatch (Case B) -->
    <div id="screen-mismatch" class="screen">
      <div class="status-icon">&#x26A0;</div>
      <div style="font-size:1.1rem;font-weight:700;margin-bottom:.5rem;">Session not started</div>
      <div class="landing-status">The session code in your URL is not currently active.</div>
      <span class="gray-link" onclick="clearSessionAndReload()">click here to enter another session id</span>
    </div>

    <!-- Screen: name entry -->
    <div id="screen-name" class="screen">
      <input
        id="session-display"
        class="landing-input readonly"
        type="text"
        readonly
        tabindex="-1"
      />
      <input
        id="name-input"
        class="landing-input name-input"
        type="text"
        maxlength="32"
        autocomplete="off"
        placeholder="Your name"
      />
      <button id="submit-name-btn" class="landing-btn" disabled>Join</button>
      <button id="random-name-btn" class="landing-btn secondary">Use random name</button>
      <div id="name-error" class="landing-error"></div>
    </div>

    <!-- Screen: entering app -->
    <div id="screen-entering" class="screen">
      <div class="landing-status">Joining session...</div>
    </div>
  </div>

  <div id="toast" class="toast"></div>

  <script>
    // ── Constants ──
    const SESSION_CODE_RE = /^[a-z0-9]{6}$/;
    const RETRY_DELAYS = [1000, 2000, 3000, 5000, 5000]; // participant backoff
    const HOST_POLL_MS = 3000;
    const LS_UUID_KEY = 'workshop_participant_uuid';
    const LS_NAME_KEY = 'workshop_participant_name';
    const LS_CUSTOM_NAME_KEY = 'workshop_custom_name';

    const isHostTab = document.cookie.includes('is_host=1');
    const uuidStorage = isHostTab ? sessionStorage : localStorage;

    // ── State ──
    let currentScreen = 'checking';
    let sessionId = null; // from query param
    let myUUID = null;
    let toastTimer = null;

    // ── Helpers ──
    function showScreen(id) {
      document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
      document.getElementById('screen-' + id).classList.add('active');
      currentScreen = id;
    }

    function showToast(msg) {
      const t = document.getElementById('toast');
      t.textContent = msg;
      t.classList.add('show');
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => t.classList.remove('show'), 3000);
    }

    function shakeElement(el) {
      el.classList.remove('shake');
      void el.offsetWidth; // reflow
      el.classList.add('shake');
    }

    function normalizeCode(raw) {
      return String(raw || '').toLowerCase().replace(/[^a-z0-9]/g, '').slice(0, 6);
    }

    function getOrCreateUUID() {
      let uid = uuidStorage.getItem(LS_UUID_KEY);
      if (!uid) {
        uid = crypto.randomUUID();
        uuidStorage.setItem(LS_UUID_KEY, uid);
      }
      return uid;
    }

    function clearSessionAndReload() {
      window.location.href = '/';
    }

    function enterApp(sessionCode, name) {
      // Store name so participant.js picks it up
      const nameStorage = isHostTab ? sessionStorage : localStorage;
      nameStorage.setItem(LS_NAME_KEY, name);
      window.location.href = '/' + sessionCode;
    }

    // ── API calls ──
    async function checkIsActiveSession() {
      const resp = await fetch('/api/is-active-session', { cache: 'no-store' });
      if (!resp.ok) throw new Error('request-failed');
      const data = await resp.json();
      return data.active === true;
    }

    async function validateSessionCode(code) {
      const resp = await fetch('/' + code + '/api/status', { cache: 'no-store' });
      return resp.ok;
    }

    async function registerParticipant(code, uuid) {
      const resp = await fetch('/' + code + '/api/participant/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Participant-ID': uuid },
        body: '{}',
      });
      if (!resp.ok) return null;
      return await resp.json(); // { name, avatar }
    }

    async function renameParticipant(code, uuid, newName) {
      const resp = await fetch('/' + code + '/api/participant/name', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-Participant-ID': uuid },
        body: JSON.stringify({ name: newName }),
      });
      return resp.status; // 204 = ok, 409 = taken
    }

    // ── Flow: is-active-session check with retries ──
    async function runActiveSessionCheck() {
      showScreen('checking');

      for (let attempt = 0; attempt < RETRY_DELAYS.length; attempt++) {
        try {
          const active = await checkIsActiveSession();
          if (active) return true; // success
          // Response was false — no session started
          showScreen('error');
          document.getElementById('error-icon').textContent = '\u23F3';
          document.getElementById('error-title').textContent = 'No session started';
        } catch (e) {
          // Request failed — host not connected
          showScreen('error');
          document.getElementById('error-icon').textContent = '\u26A0';
          document.getElementById('error-title').textContent = 'Host not connected';
        }

        // Show countdown
        const delay = RETRY_DELAYS[attempt];
        const retryEl = document.getElementById('error-retry-status');
        const retryNum = attempt + 1;
        retryEl.textContent = 'Retrying (' + retryNum + '/' + RETRY_DELAYS.length + ')...';

        await new Promise(r => setTimeout(r, delay));
      }

      // Retries exhausted
      document.getElementById('error-retry-status').textContent = 'Could not connect. Reload to try again.';
      return false;
    }

    // ── Flow: code entry (Case A) ──
    function setupCodeEntry() {
      showScreen('code');
      const input = document.getElementById('code-input');
      input.value = '';
      input.focus();

      input.addEventListener('input', () => {
        const code = normalizeCode(input.value);
        if (input.value !== code) input.value = code;
        document.getElementById('code-error').textContent = '';

        if (SESSION_CODE_RE.test(code)) {
          tryValidateCode(code);
        }
      });

      input.addEventListener('paste', (e) => {
        const pasted = (e.clipboardData || window.clipboardData).getData('text').trim();
        const urlMatch = pasted.match(/^https?:\/\/[^/]+\/([a-zA-Z0-9]{4,8})\/?$/);
        if (urlMatch) {
          e.preventDefault();
          input.value = normalizeCode(urlMatch[1]);
          input.dispatchEvent(new Event('input'));
        }
      });
    }

    async function tryValidateCode(code) {
      const valid = await validateSessionCode(code);
      if (valid) {
        // Redirect with session_id param — page reloads and continues flow
        window.location.href = '/?session_id=' + code;
      } else {
        const input = document.getElementById('code-input');
        shakeElement(input);
        input.style.color = 'var(--danger)';
        setTimeout(() => { input.style.color = ''; }, 1500);
        showToast('Invalid session code');
        document.getElementById('code-error').textContent = 'Invalid session code';
      }
    }

    // ── Flow: UUID / rejoin check ──
    async function tryRejoinOrRegister(code) {
      myUUID = getOrCreateUUID();

      // Try register — idempotent for returning participants
      const result = await registerParticipant(code, myUUID);
      if (!result) {
        // Registration failed — show name entry anyway
        setupNameEntry(code);
        return;
      }

      // Check if this UUID was already in the session (idempotent return)
      // If the name is a LOTR name and not a custom name, treat as new registration
      const storedCustom = localStorage.getItem(LS_CUSTOM_NAME_KEY);
      const storedName = localStorage.getItem(LS_NAME_KEY);

      if (storedCustom && storedName) {
        // Returning participant with custom name — enter directly
        // The register call already re-registered them
        if (isHostTab) {
          enterApp(code, storedName + ' (host)');
        } else {
          enterApp(code, storedName);
        }
        return;
      }

      if (isHostTab) {
        // Host: use assigned name + "(host)" suffix, enter immediately
        enterApp(code, result.name + ' (host)');
        return;
      }

      // New participant — show name entry with pre-filled server name
      setupNameEntry(code, result.name);
    }

    // ── Flow: name entry screen ──
    function setupNameEntry(code, suggestedName) {
      showScreen('name');
      sessionId = code;

      document.getElementById('session-display').value = code;

      const nameInput = document.getElementById('name-input');
      const submitBtn = document.getElementById('submit-name-btn');
      const randomBtn = document.getElementById('random-name-btn');

      if (suggestedName) {
        nameInput.value = suggestedName;
        submitBtn.disabled = false;
      }
      nameInput.focus();

      nameInput.addEventListener('input', () => {
        submitBtn.disabled = !nameInput.value.trim();
        document.getElementById('name-error').textContent = '';
      });

      nameInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !submitBtn.disabled) submitName();
      });

      submitBtn.addEventListener('click', submitName);
      randomBtn.addEventListener('click', useRandomName);
    }

    async function submitName() {
      const nameInput = document.getElementById('name-input');
      const name = nameInput.value.trim().slice(0, 32);
      if (!name) return;

      if (!myUUID) myUUID = getOrCreateUUID();

      // First register (idempotent)
      await registerParticipant(sessionId, myUUID);

      // Then rename
      const status = await renameParticipant(sessionId, myUUID, name);
      if (status === 409) {
        shakeElement(nameInput);
        showToast('Name taken');
        document.getElementById('name-error').textContent = 'Name taken';
        return;
      }

      localStorage.setItem(LS_NAME_KEY, name);
      localStorage.setItem(LS_CUSTOM_NAME_KEY, '1');
      enterApp(sessionId, name);
    }

    async function useRandomName() {
      if (!myUUID) myUUID = getOrCreateUUID();

      const result = await registerParticipant(sessionId, myUUID);
      if (result) {
        enterApp(sessionId, result.name);
      }
    }

    // ── Host machine detection: poll local daemon ──
    function pollLocalDaemon() {
      function tryFetch() {
        fetch('http://localhost:1234/api/session/active', { signal: AbortSignal.timeout(800) })
          .then(r => r.ok ? r.json() : null)
          .then(data => {
            const code = normalizeCode(data && data.session_id);
            if (!SESSION_CODE_RE.test(code)) return;
            // Set session_id and reload
            if (!sessionId || sessionId !== code) {
              window.location.href = '/?session_id=' + code;
            }
          })
          .catch(() => {}); // daemon not running — silent
      }

      tryFetch();
      setInterval(tryFetch, 1000);
    }

    // ── Main flow ──
    async function main() {
      // Parse query params
      const params = new URLSearchParams(window.location.search);
      sessionId = normalizeCode(params.get('session_id') || '');
      if (!SESSION_CODE_RE.test(sessionId)) sessionId = null;

      // Start host machine detection in background
      pollLocalDaemon();

      // Step 1: Check if any session is active
      const active = await runActiveSessionCheck();
      if (!active) return; // retries exhausted, screen already shows error

      // Step 2: Do we have a session_id?
      if (!sessionId) {
        // Case A: no session_id — show code entry
        setupCodeEntry();
        return;
      }

      // Step 3: Validate session_id matches active session
      const valid = await validateSessionCode(sessionId);
      if (!valid) {
        // Case B: session_id doesn't match
        showScreen('mismatch');
        return;
      }

      // Case C: session_id is valid
      // Step 4: Check session type (conference not supported yet)
      // For now, proceed assuming workshop (conference check can be added later via status response)

      // Step 5: UUID / rejoin / name entry
      showScreen('entering');
      await tryRejoinOrRegister(sessionId);
    }

    main();
  </script>

  <script src="/static/version.js"></script>
  <script src="/static/work-hours.js"></script>
  <script src="/static/version-age.js"></script>
  <script src="/static/version-reload.js"></script>
  <div class="version-tag" id="version-tag"></div>
  <script>window.renderDeployAge && window.renderDeployAge('version-tag');</script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add static/landing.html
git commit -m "feat: rewrite landing page with multi-screen join flow per activity diagram"
```

---

### Task 3: Update `participant.js` WS disconnect redirect

**Files:**
- Modify: `static/participant.js:2802-2808` (ws.onclose handler)

The current WS close handler redirects to `/?code={sessionId}&retry=1`. Change it to redirect to `/?session_id={sessionId}`.

- [ ] **Step 1: Update the onclose handler**

Find the `ws.onclose` handler in the `connectWS` function (around line 2802):

```javascript
// BEFORE:
ws.onclose = (event) => {
    if (event.code === 1008 && !pendingRedirect) {
      window.location.href = `/?code=${encodeURIComponent(sessionId)}&retry=1`;
      return;
    }
    if (!pendingRedirect) setTimeout(() => connectWS(myName), 3000);
};

// AFTER:
ws.onclose = (event) => {
    if (event.code === 1008 && !pendingRedirect) {
      window.location.href = `/?session_id=${encodeURIComponent(sessionId)}`;
      return;
    }
    if (!pendingRedirect) setTimeout(() => connectWS(myName), 3000);
};
```

- [ ] **Step 2: Verify the landing page handles `?session_id=` param**

The new landing.html already reads `session_id` from query params in its `main()` function. No additional changes needed.

- [ ] **Step 3: Commit**

```bash
git add static/participant.js
git commit -m "feat: redirect to /?session_id= on WS disconnect instead of /?code="
```

---

### Task 4: Hermetic E2E tests — all branches

**Files:**
- Create: `tests/docker/test_participant_join_flow.py`

These tests run inside Docker with the real backend + daemon + Playwright. They use the existing `session_utils.py` infrastructure.

- [ ] **Step 1: Write the test file**

```python
"""
Hermetic E2E tests for the participant join flow.

Tests all branches of the activity diagram in docs/participant-join-activity.puml:
- is-active-session check (3-way: failed/false/true)
- Code entry (Case A): valid/invalid codes
- Session mismatch (Case B): stale session_id
- Rejoin with UUID (Case C): returning participant
- Name entry: submit custom name, random name, name taken
- Host auto-join via localhost:1234
"""

import os
import time
import json

import pytest
from playwright.sync_api import sync_playwright, expect

from tests.docker.session_utils import (
    BASE,
    DAEMON_BASE,
    HOST_USER,
    HOST_PASS,
    fresh_session,
    daemon_has_participant,
    _get_json,
    _req,
)


@pytest.fixture(scope="module")
def pw():
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="module")
def browser(pw):
    b = pw.chromium.launch(headless=True)
    yield b
    b.close()


@pytest.fixture
def session_id():
    return fresh_session("JoinFlowTest")


def _open_landing(browser, query_params=""):
    """Open the landing page in a fresh context."""
    ctx = browser.new_context()
    page = ctx.new_page()
    url = BASE + "/" + ("?" + query_params if query_params else "")
    page.goto(url, wait_until="networkidle")
    return page, ctx


def _open_landing_with_session(browser, session_id):
    """Open landing page with session_id query param."""
    return _open_landing(browser, f"session_id={session_id}")


# ═══════════════════════════════════════════════════════════════════
# is-active-session check
# ═══════════════════════════════════════════════════════════════════


class TestIsActiveSessionCheck:
    """Tests for the initial is-active-session check on the landing page."""

    def test_active_session_shows_code_entry(self, browser, session_id):
        """When a session is active and no session_id param, show code entry screen."""
        page, ctx = _open_landing(browser)
        try:
            # Should pass the is-active-session check and show code entry
            code_input = page.locator("#code-input")
            expect(code_input).to_be_visible(timeout=15000)
        finally:
            ctx.close()

    def test_no_active_session_shows_error(self, browser):
        """When no session is active, show 'No session started' after retries."""
        # End any active session first
        try:
            _req("POST", f"{DAEMON_BASE}/api/session/end")
        except Exception:
            pass
        time.sleep(1)

        page, ctx = _open_landing(browser)
        try:
            # Should show error after retries (wait for retries to exhaust: ~16s)
            error_title = page.locator("#error-title")
            expect(error_title).to_contain_text("No session started", timeout=25000)
            retry_status = page.locator("#error-retry-status")
            expect(retry_status).to_contain_text("Could not connect", timeout=30000)
        finally:
            ctx.close()
            # Restore a session for other tests
            fresh_session("AfterNoSession")


# ═══════════════════════════════════════════════════════════════════
# Code entry (Case A)
# ═══════════════════════════════════════════════════════════════════


class TestCodeEntry:
    """Tests for the session code entry screen."""

    def test_valid_code_redirects(self, browser, session_id):
        """Entering a valid 6-digit session code redirects to ?session_id=."""
        page, ctx = _open_landing(browser)
        try:
            code_input = page.locator("#code-input")
            expect(code_input).to_be_visible(timeout=15000)

            # Type the valid session code
            code_input.fill(session_id)

            # Should redirect to /?session_id={code} and then proceed to name entry
            # or entering screen
            page.wait_for_url(f"*session_id={session_id}*", timeout=10000)
        finally:
            ctx.close()

    def test_invalid_code_shakes_input(self, browser, session_id):
        """Entering an invalid session code shakes the input and shows error."""
        page, ctx = _open_landing(browser)
        try:
            code_input = page.locator("#code-input")
            expect(code_input).to_be_visible(timeout=15000)

            # Type an invalid code
            code_input.fill("xxxxxx")

            # Should show error toast and error message
            toast = page.locator("#toast")
            expect(toast).to_have_class(/show/, timeout=5000)
            expect(toast).to_contain_text("Invalid session code")

            code_error = page.locator("#code-error")
            expect(code_error).to_contain_text("Invalid session code")
        finally:
            ctx.close()


# ═══════════════════════════════════════════════════════════════════
# Session mismatch (Case B)
# ═══════════════════════════════════════════════════════════════════


class TestSessionMismatch:
    """Tests for Case B: session_id in URL doesn't match active session."""

    def test_stale_session_id_shows_mismatch(self, browser, session_id):
        """A stale/wrong session_id shows 'Session not started' screen."""
        page, ctx = _open_landing_with_session(browser, "zzzzzz")
        try:
            mismatch = page.locator("#screen-mismatch")
            expect(mismatch).to_be_visible(timeout=15000)
            expect(mismatch).to_contain_text("Session not started")
        finally:
            ctx.close()

    def test_mismatch_clear_link_goes_to_code_entry(self, browser, session_id):
        """Clicking 'enter another session id' clears param and shows code entry."""
        page, ctx = _open_landing_with_session(browser, "zzzzzz")
        try:
            mismatch = page.locator("#screen-mismatch")
            expect(mismatch).to_be_visible(timeout=15000)

            # Click the gray link
            page.locator(".gray-link").click()

            # Should navigate to / without session_id
            page.wait_for_url(BASE + "/", timeout=5000)

            # Should show code entry (after is-active check passes)
            code_input = page.locator("#code-input")
            expect(code_input).to_be_visible(timeout=15000)
        finally:
            ctx.close()


# ═══════════════════════════════════════════════════════════════════
# Name entry
# ═══════════════════════════════════════════════════════════════════


class TestNameEntry:
    """Tests for the name entry screen (workshop mode)."""

    def test_valid_session_shows_name_entry(self, browser, session_id):
        """A valid session_id leads to name entry screen."""
        page, ctx = _open_landing_with_session(browser, session_id)
        try:
            name_input = page.locator("#name-input")
            expect(name_input).to_be_visible(timeout=15000)

            # Session code should be displayed read-only
            session_display = page.locator("#session-display")
            expect(session_display).to_have_value(session_id)
        finally:
            ctx.close()

    def test_submit_custom_name_enters_app(self, browser, session_id):
        """Submitting a custom name navigates to the participant app."""
        page, ctx = _open_landing_with_session(browser, session_id)
        try:
            name_input = page.locator("#name-input")
            expect(name_input).to_be_visible(timeout=15000)

            name_input.fill("TestAlice")
            page.locator("#submit-name-btn").click()

            # Should redirect to /{session_id}
            page.wait_for_url(f"**/{session_id}**", timeout=10000)

            # Participant should be in the app
            expect(page.locator("#main-screen")).to_be_visible(timeout=10000)
        finally:
            ctx.close()

    def test_random_name_enters_app(self, browser, session_id):
        """Clicking 'Use random name' enters the app with a server-assigned name."""
        page, ctx = _open_landing_with_session(browser, session_id)
        try:
            random_btn = page.locator("#random-name-btn")
            expect(random_btn).to_be_visible(timeout=15000)
            random_btn.click()

            # Should redirect to /{session_id}
            page.wait_for_url(f"**/{session_id}**", timeout=10000)

            # Participant should be in the app
            expect(page.locator("#main-screen")).to_be_visible(timeout=10000)
        finally:
            ctx.close()

    def test_duplicate_name_shakes_input(self, browser, session_id):
        """Submitting a name that's already taken shakes the input."""
        # First participant takes the name "Bob"
        page1, ctx1 = _open_landing_with_session(browser, session_id)
        try:
            name_input1 = page1.locator("#name-input")
            expect(name_input1).to_be_visible(timeout=15000)
            name_input1.fill("Bob")
            page1.locator("#submit-name-btn").click()
            page1.wait_for_url(f"**/{session_id}**", timeout=10000)
        finally:
            ctx1.close()

        # Second participant tries the same name
        page2, ctx2 = _open_landing_with_session(browser, session_id)
        try:
            name_input2 = page2.locator("#name-input")
            expect(name_input2).to_be_visible(timeout=15000)
            name_input2.fill("Bob")
            page2.locator("#submit-name-btn").click()

            # Should show toast with "Name taken"
            toast = page2.locator("#toast")
            expect(toast).to_have_class(/show/, timeout=5000)
            expect(toast).to_contain_text("Name taken")

            # Should still be on the name entry screen
            expect(name_input2).to_be_visible()
        finally:
            ctx2.close()

    def test_join_button_disabled_when_empty(self, browser, session_id):
        """The Join button is disabled when name input is empty."""
        page, ctx = _open_landing_with_session(browser, session_id)
        try:
            name_input = page.locator("#name-input")
            expect(name_input).to_be_visible(timeout=15000)

            submit_btn = page.locator("#submit-name-btn")
            expect(submit_btn).to_be_disabled()

            # Type something — button should enable
            name_input.fill("Test")
            expect(submit_btn).to_be_enabled()

            # Clear — button should disable again
            name_input.fill("")
            expect(submit_btn).to_be_disabled()
        finally:
            ctx.close()


# ═══════════════════════════════════════════════════════════════════
# Rejoin with UUID
# ═══════════════════════════════════════════════════════════════════


class TestRejoin:
    """Tests for returning participants with stored UUID."""

    def test_returning_participant_auto_enters(self, browser, session_id):
        """A participant who already joined can return and auto-enter."""
        # First visit: join with a custom name
        ctx1 = browser.new_context()
        page1 = ctx1.new_page()
        page1.goto(f"{BASE}/?session_id={session_id}", wait_until="networkidle")

        name_input = page1.locator("#name-input")
        expect(name_input).to_be_visible(timeout=15000)
        name_input.fill("ReturningUser")
        page1.locator("#submit-name-btn").click()
        page1.wait_for_url(f"**/{session_id}**", timeout=10000)
        expect(page1.locator("#main-screen")).to_be_visible(timeout=10000)

        # Get the stored UUID and name from localStorage
        uuid = page1.evaluate("localStorage.getItem('workshop_participant_uuid')")
        assert uuid, "UUID should be stored in localStorage"
        ctx1.close()

        # Second visit: same UUID in localStorage should auto-enter
        ctx2 = browser.new_context()
        page2 = ctx2.new_page()
        # Inject the UUID into localStorage before navigating
        page2.goto(f"{BASE}/", wait_until="domcontentloaded")
        page2.evaluate(f"localStorage.setItem('workshop_participant_uuid', '{uuid}')")
        page2.evaluate(f"localStorage.setItem('workshop_participant_name', 'ReturningUser')")
        page2.evaluate(f"localStorage.setItem('workshop_custom_name', '1')")
        page2.goto(f"{BASE}/?session_id={session_id}", wait_until="networkidle")

        # Should auto-enter without showing name entry
        page2.wait_for_url(f"**/{session_id}**", timeout=15000)
        expect(page2.locator("#main-screen")).to_be_visible(timeout=10000)
        ctx2.close()


# ═══════════════════════════════════════════════════════════════════
# is-active-session endpoint
# ═══════════════════════════════════════════════════════════════════


class TestIsActiveSessionEndpoint:
    """Tests for the GET /api/is-active-session Railway endpoint."""

    def test_returns_true_when_session_active(self, session_id):
        """Endpoint returns {active: true} when a session is running."""
        data = _get_json(f"{BASE}/api/is-active-session")
        assert data.get("active") is True

    def test_returns_false_when_no_session(self):
        """Endpoint returns {active: false} when no session is running."""
        try:
            _req("POST", f"{DAEMON_BASE}/api/session/end")
        except Exception:
            pass
        time.sleep(2)
        data = _get_json(f"{BASE}/api/is-active-session")
        assert data.get("active") is False
        # Restore session
        fresh_session("AfterEndpointTest")
```

- [ ] **Step 2: Run the tests locally in Docker**

```bash
bash tests/docker/run-hermetic.sh tests/docker/test_participant_join_flow.py -v
```

Expected: All tests should pass. If any fail, fix the landing page or endpoint code.

- [ ] **Step 3: Commit**

```bash
git add tests/docker/test_participant_join_flow.py
git commit -m "test: add hermetic e2e tests for all participant join flow branches"
```

---

### Task 5: Update existing tests and clean up

**Files:**
- Modify: `tests/docker/session_utils.py` (if needed for query param changes)
- Modify: `tests/docker/test_session_flow.py` (update landing page assertions)
- Modify: any other test files that rely on old `/?code=` redirect format

- [ ] **Step 1: Search for references to old redirect format**

```bash
grep -r "code=" tests/docker/ --include="*.py" -l
grep -r "retry=1" tests/docker/ --include="*.py" -l
grep -r "error=invalid" static/ --include="*.js" -l
```

- [ ] **Step 2: Update any tests that check for `/?code=` or `/?retry=1` URLs**

Change to expect `/?session_id=` format.

- [ ] **Step 3: Verify existing hermetic tests still pass**

```bash
bash tests/docker/run-hermetic.sh -v
```

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: update existing tests for new landing page flow"
```

---

### Task 6: Final integration verification

- [ ] **Step 1: Run full hermetic test suite**

```bash
bash tests/docker/run-hermetic.sh -v
```

All tests (old + new) must pass.

- [ ] **Step 2: Run daemon tests**

```bash
bash tests/run-daemon-tests.sh
```

- [ ] **Step 3: Run check-all**

```bash
bash tests/check-all.sh
```

- [ ] **Step 4: Push to master**

```bash
git push origin master
```
