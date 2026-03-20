# Browser Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fire OS-level browser notifications to participants when the host opens a new poll, Q&A, or word cloud — but only when their tab is backgrounded.

**Architecture:** Pure frontend change. Two helpers added to `participant.js` (`requestNotificationPermission`, `notifyIfHidden`). Transition detection runs inside the existing `case 'state':` handler by comparing current vs previous `pollActive` and `current_activity`. Permission is requested on Join click for new users; returning (auto-join) users get a 🔔 button in the status bar.

**Tech Stack:** Vanilla JS, Web Notifications API (`Notification`), Playwright for e2e tests.

---

## Files Changed

| File | Change |
|---|---|
| `static/participant.html` | Add hidden `🔔` button to `.status-right` |
| `static/participant.js` | Add 4 state vars, 2 helpers, wire permission into join/onopen, add transition detection in `handleMessage` |
| `test_e2e.py` | New test class for notification button visibility |
| `pages/participant_page.py` | No changes needed |

---

## Task 1: Add the 🔔 button to participant.html

**Files:**
- Modify: `static/participant.html`

- [ ] **Step 1: Add the button inside `.status-right`**

Locate this exact block in `static/participant.html`:

```html
      <span class="status-right">
        <span id="pax-count"></span>
        <button id="leave-btn" title="Change name">☢️ Leave</button>
      </span>
```

Replace it with:

```html
      <span class="status-right">
        <span id="pax-count"></span>
        <button id="notif-btn" title="Enable notifications" style="display:none">🔔</button>
        <button id="leave-btn" title="Change name">☢️ Leave</button>
      </span>
```

- [ ] **Step 2: Commit**

```bash
git add static/participant.html
git commit -m "feat: add hidden notification enable button to participant status bar"
```

---

## Task 2: Add state variables and helpers to participant.js

**Files:**
- Modify: `static/participant.js`

- [ ] **Step 1: Add 4 tracking variables after the existing variable block (line 32)**

Locate this exact line in `static/participant.js`:

```js
  let _qaToastTimeout = null;
```

Replace it with:

```js
  let _qaToastTimeout = null;
  let _prevPollActive = false;
  let _prevActivity = null;
  let _stateInitialised = false;   // skip notifications on first state (join mid-session)
  let _notifBtnBound = false;      // prevent re-binding on reconnect
```

- [ ] **Step 2: Add `requestNotificationPermission()` and `notifyIfHidden()` helpers**

Locate this exact block:

```js
  function escHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }
```

Replace it with:

```js
  function escHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  async function requestNotificationPermission() {
    if (!('Notification' in window)) return;
    if (Notification.permission !== 'default') return;
    await Notification.requestPermission();
    const btn = document.getElementById('notif-btn');
    if (btn) btn.style.display = 'none';
  }

  function notifyIfHidden(title, body) {
    if (!document.hidden) return;
    if (Notification.permission !== 'granted') return;
    new Notification(title, { body });
  }
```

- [ ] **Step 3: Commit**

```bash
git add static/participant.js
git commit -m "feat: add requestNotificationPermission and notifyIfHidden helpers"
```

---

## Task 3: Wire permission request into join flow and auto-join

**Files:**
- Modify: `static/participant.js`

- [ ] **Step 1: Write failing tests**

In `test_e2e.py`, add a new test class at the bottom of the file (before or after existing classes):

```python
class TestNotifications:
    """Browser notification button behaviour."""

    def test_notif_btn_hidden_on_load(self, server_url):
        """The 🔔 button is hidden before any join."""
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(server_url)
            expect(page.locator("#notif-btn")).to_be_hidden()
            browser.close()

    def test_notif_btn_hidden_after_fresh_join(self, server_url):
        """After a fresh join (user gesture), no 🔔 button shown —
        permission was requested inline via the join gesture, so
        Notification.permission is already 'granted' when ws.onopen runs."""
        with sync_playwright() as p:
            browser = p.chromium.launch()
            # Grant notifications so requestPermission() resolves immediately
            ctx = browser.new_context(permissions=["notifications"])
            page = ctx.new_page()
            page.goto(server_url)
            ParticipantPage(page).join("NotifFreshJoiner")
            # ws.onopen sees permission !== 'default' → button stays hidden
            expect(page.locator("#notif-btn")).to_be_hidden()
            browser.close()

    def test_notif_btn_visible_for_returning_participant(self, server_url):
        """Auto-joining participant (saved name in localStorage) sees the 🔔
        button when notification permission has not yet been decided."""
        with sync_playwright() as p:
            browser = p.chromium.launch()
            # Default context: Notification.permission === 'default' in Chromium headless
            ctx = browser.new_context()
            page = ctx.new_page()
            page.goto(server_url)
            # Simulate returning participant by seeding localStorage, then reload
            page.evaluate("localStorage.setItem('workshop_participant_name', 'ReturningUser')")
            page.reload()
            # After auto-join ws.onopen fires and sees permission === 'default' → show button
            expect(page.locator("#notif-btn")).to_be_visible(timeout=5000)
            browser.close()
```

- [ ] **Step 2: Run to verify tests fail**

```bash
pytest test_e2e.py::TestNotifications -v
```

Expected: `test_notif_btn_hidden_after_fresh_join` and `test_notif_btn_visible_for_returning_participant` fail — button logic not yet wired.

- [ ] **Step 3: Wire `requestNotificationPermission` into the join gesture handlers**

Locate these exact lines in `static/participant.js`:

```js
  document.getElementById('join-btn').addEventListener('click', join);
  nameInput.addEventListener('keydown', e => { if (e.key === 'Enter') join(); });
```

Replace with:

```js
  document.getElementById('join-btn').addEventListener('click', () => { join(); requestNotificationPermission(); });
  nameInput.addEventListener('keydown', e => { if (e.key === 'Enter') { join(); requestNotificationPermission(); } });
```

- [ ] **Step 4: Reset `_stateInitialised` and show 🔔 button in `connectWS` / `ws.onopen`**

Locate this exact line in `static/participant.js`:

```js
  function connectWS(name) {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
```

Replace with:

```js
  function connectWS(name) {
    _stateInitialised = false;
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
```

Then locate this exact block inside `ws.onopen`:

```js
      document.getElementById('display-name').textContent = myName;

      const loc = await resolveLocation();
```

Replace with:

```js
      document.getElementById('display-name').textContent = myName;

      // Show 🔔 button for auto-joiners who haven't been asked for permission yet
      if ('Notification' in window && Notification.permission === 'default' && !_notifBtnBound) {
        _notifBtnBound = true;
        const btn = document.getElementById('notif-btn');
        if (btn) { btn.style.display = ''; btn.onclick = requestNotificationPermission; }
      }

      const loc = await resolveLocation();
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest test_e2e.py::TestNotifications -v
```

Expected: all 3 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add static/participant.js test_e2e.py
git commit -m "feat: wire notification permission request on join and for auto-joiners"
```

---

## Task 4: Add transition detection in handleMessage

**Files:**
- Modify: `static/participant.js`

- [ ] **Step 1: Write failing test**

Add to `TestNotifications` in `test_e2e.py`:

```python
def test_no_spurious_notification_on_join_mid_poll(self, server_url):
    """Joining while a poll is already active must NOT fire a notification
    (first state message seeds tracking state, doesn't trigger)."""
    import json, urllib.request, base64
    creds = base64.b64encode(b"host:testpass").decode()
    host_headers = {"Authorization": f"Basic {creds}", "Content-Type": "application/json"}

    # Create and open a poll via API before participant joins
    req = urllib.request.Request(
        f"{server_url}/api/poll",
        data=json.dumps({"question": "Notif test Q", "options": ["A", "B"]}).encode(),
        headers=host_headers, method="POST",
    )
    urllib.request.urlopen(req)
    req2 = urllib.request.Request(
        f"{server_url}/api/poll/status",
        data=json.dumps({"active": True}).encode(),
        headers=host_headers, method="POST",
    )
    urllib.request.urlopen(req2)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(permissions=["notifications"])

        # Inject Notification mock BEFORE page load using add_init_script.
        # Also force document.hidden=true so notifyIfHidden() doesn't suppress
        # the notification before it reaches new Notification() — this is what
        # makes the test actually fail without the _stateInitialised guard.
        ctx.add_init_script("""
          window._notifFired = false;
          const _OrigNotif = window.Notification;
          window.Notification = function(t, o) {
            window._notifFired = true;
            return new _OrigNotif(t, o);
          };
          Object.defineProperty(window.Notification, 'permission', {
            get: () => _OrigNotif.permission
          });
          window.Notification.requestPermission = _OrigNotif.requestPermission.bind(_OrigNotif);
          // Force tab to appear hidden so notifyIfHidden() doesn't bail early
          Object.defineProperty(document, 'hidden', { get: () => true, configurable: true });
        """)

        page = ctx.new_page()
        page.goto(server_url)
        ParticipantPage(page).join("NotifJoinMid")
        page.wait_for_timeout(1000)  # let state message arrive

        notif_fired = page.evaluate("window._notifFired")
        assert not notif_fired, "No notification should fire when joining mid-poll"
        browser.close()
```

- [ ] **Step 2: Run to verify test fails**

```bash
pytest test_e2e.py::TestNotifications::test_no_spurious_notification_on_join_mid_poll -v
```

Expected: FAIL — notification fires without the `_stateInitialised` guard.

- [ ] **Step 3: Add transition detection in `case 'state':`**

Locate this exact block in `static/participant.js`:

```js
      case 'state':
        versionReloadGuard && versionReloadGuard.check(msg.backend_version);
        if (msg.poll?.id !== currentPoll?.id) {
```

Replace with:

```js
      case 'state':
        versionReloadGuard && versionReloadGuard.check(msg.backend_version);
        if (!_stateInitialised) {
          // First message after connect: seed tracking state, fire no notification
          _prevPollActive = msg.poll_active;
          _prevActivity   = msg.current_activity;
          _stateInitialised = true;
        } else {
          if (!_prevPollActive && msg.poll_active && msg.poll) {
            notifyIfHidden('🗳️ New poll!', msg.poll.question);
          }
          if (_prevActivity !== 'qa' && msg.current_activity === 'qa') {
            notifyIfHidden('❓ Q&A is open', 'Tap to ask or upvote questions');
          }
          if (_prevActivity !== 'wordcloud' && msg.current_activity === 'wordcloud') {
            notifyIfHidden('☁️ Word cloud is open', 'Tap to share your thoughts');
          }
          _prevPollActive = msg.poll_active;
          _prevActivity   = msg.current_activity;
        }
        if (msg.poll?.id !== currentPoll?.id) {
```

- [ ] **Step 4: Run all notification tests**

```bash
pytest test_e2e.py::TestNotifications -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
pytest test_e2e.py test_main.py -v
```

Expected: all existing tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add static/participant.js test_e2e.py
git commit -m "feat: browser notifications for participants on new poll/Q&A/word cloud activity"
```

---

## Task 5: Manual smoke test + close issue

- [ ] **Step 1: Manual verification — new joiner path**

1. Open `http://localhost:8000/` in Chrome (fresh profile so permission is `'default'`)
2. Enter a name and click **Join session** → browser prompts for notification permission → click **Allow**
3. Switch to another tab to background the workshop tab
4. From host panel, open a new poll
5. Verify: OS notification appears saying "🗳️ New poll!" with the question text
6. Repeat for Q&A and word cloud activity switches

- [ ] **Step 2: Manual verification — returning participant path**

1. Refresh the page (name is remembered → auto-join, no permission prompt)
2. The 🔔 button should appear in the status bar (if permission was not yet granted in this profile)
3. Click 🔔 → browser prompts → Allow
4. Background the tab, host opens a poll → notification fires

- [ ] **Step 3: Push and update backlog**

```bash
git push origin victorrentea/browser-push-notifications
```

Add to `backlog.md`:
```
- [ ] feat: browser push notifications — participant UI requests permission on Join; 🔔 button for auto-joiners; notifies on new poll/Q&A/word cloud when tab is hidden
```
