# Browser Notifications for Participants — Design Spec

**Date:** 2026-03-20
**Issue:** #4
**Status:** Approved

---

## Goal

When participants have the workshop tab open but are distracted (tab in background, device screen off), the app should call their attention via a browser notification whenever the host starts a new activity.

---

## Scope

Changes are confined to `static/participant.html` and `static/participant.js`. No backend changes required. No new files.

---

## Notification Triggers

A notification fires **only when `document.hidden === true`** (tab is backgrounded or window is minimised). If the tab is already visible, no notification is shown — the UI update is sufficient.

| Event | Title | Body |
|---|---|---|
| Poll opens (voting becomes active) | 🗳️ New poll! | The poll question text |
| Q&A activity opens | ❓ Q&A is open | "Tap to ask or upvote questions" |
| Word cloud activity opens | ☁️ Word cloud is open | "Tap to share your thoughts" |

Notifications are **not** fired for:
- Individual Q&A questions submitted by participants
- Poll closing / results
- Score updates

---

## Permission Flow

### New joiners (manual Join click)
`Notification.requestPermission()` is called inside `join()`, which executes inside a user gesture handler. Browsers allow this. No button shown.

### Returning participants (auto-join on page load)
The `join()` function is called programmatically when a saved name is found in `localStorage` — this is not a user gesture, so `requestPermission()` would be blocked by the browser. Instead:

1. After `ws.onopen`, check `Notification.permission`.
2. If `'default'` (not yet asked): show a `🔔 Enable notifications` button in the status bar.
3. The button's `onclick` calls `requestNotificationPermission()` (user gesture ✓) and then hides itself regardless of the result.
4. If permission is already `'granted'` or `'denied'`: button stays hidden.

---

## Implementation Details

### HTML change (`participant.html`)

Add the button inside the `.status-bar` `.status-right` span, initially hidden:

```html
<button id="notif-btn" title="Enable notifications" style="display:none">🔔</button>
```

### New variables (`participant.js`)

```js
let _prevPollActive = false;
let _prevActivity = null;
let _stateInitialised = false;   // suppresses false-positive on first state message
let _notifBtnBound = false;      // prevents re-binding on reconnect
```

### Permission helper

```js
async function requestNotificationPermission() {
  if (!('Notification' in window)) return;
  if (Notification.permission !== 'default') return;
  await Notification.requestPermission();
  const btn = document.getElementById('notif-btn');
  if (btn) btn.style.display = 'none';
}
```

Called from:
- `join-btn` click handler and Enter key in `nameInput` — for new joiners (user gesture ✓)
- `notif-btn` onclick — for auto-joiners (user gesture ✓)
- **Not** called from the programmatic `join()` body itself, because `join()` is also invoked at page load for auto-joiners (not a user gesture).

### Notification helper

SVG icons are silently dropped by most OS-level notification systems (Chrome, Windows, macOS). To keep things simple and avoid a 404 or blank icon, the `icon` field is omitted:

```js
function notifyIfHidden(title, body) {
  if (!document.hidden) return;
  if (Notification.permission !== 'granted') return;
  new Notification(title, { body });
}
```

### Button visibility after auto-join (`ws.onopen`)

Only shown once per page load. The `_notifBtnBound` flag prevents re-binding on reconnects (ws.onopen fires again on each auto-reconnect):

```js
if ('Notification' in window && Notification.permission === 'default' && !_notifBtnBound) {
  _notifBtnBound = true;
  const btn = document.getElementById('notif-btn');
  btn.style.display = '';
  btn.onclick = requestNotificationPermission;
}
```

### Reset `_stateInitialised` on new connection

At the top of `connectWS()`, reset the initialisation guard so reconnects don't fire spurious notifications:

```js
_stateInitialised = false;
```

### Transition detection in `handleMessage()` — `case 'state':`

The first `state` message after connecting initialises the tracking variables without firing any notification. This prevents a false-positive when a participant joins a session mid-activity. The flag is reset in `connectWS()` so reconnects behave the same way.

```js
if (!_stateInitialised) {
  // Seed tracking state from current server state — no notification
  _prevPollActive = msg.poll_active;
  _prevActivity = msg.current_activity;
  _stateInitialised = true;
} else {
  // Detect transitions
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
  _prevActivity = msg.current_activity;
}
```

---

## Graceful Degradation

- `'Notification' in window` guard on all calls — no errors on browsers without the API (e.g. iOS Safari < 16.4)
- If permission is `'denied'`: `notifyIfHidden` returns silently; no repeated prompts
- The 🔔 button is hidden if permission is already `'granted'` or `'denied'` — only shown when undecided

---

## Out of Scope

- Service Worker / Push API (works when tab is fully closed) — overkill for live sessions
- Per-question Q&A notifications — too spammy
- Notification grouping / badge counts
