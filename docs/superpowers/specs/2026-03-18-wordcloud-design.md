# Word Cloud Feature — Design Spec
**Date:** 2026-03-18
**Status:** Approved for implementation

---

## Overview

Add a live word cloud activity to the workshop tool. The host opens a word cloud round; participants (and the host) submit words; a live D3-cloud word cloud renders on every connected screen. When the host closes the round, the cloud is auto-downloaded as a PNG and disappears from all screens.

---

## Constraints & Principles

- One WebSocket connection per participant — no new connections for word cloud
- One activity at a time: poll and word cloud are mutually exclusive
- No vertical scrolling on the host screen (3-column layout redesign)
- Participant UI must be mobile-responsive
- No new infrastructure — reuse existing WS broadcast pattern

---

## Host UI — 3-Column Layout Redesign

The host panel is redesigned from its current card-stack layout into a fixed 3-column layout that avoids vertical scrolling:

| Column | Width | Content |
|--------|-------|---------|
| Left | ~25% | Controls (tabs + active tab content + status badges) |
| Center | ~50% | Current activity (idle: QR · poll: results · wordcloud: cloud) |
| Right | ~25% | Participant list with scores (always visible) |

### Left Column

- **Tab switcher** at top: `Poll` | `☁ Word Cloud`
- **Poll tab:**
  - Existing `contenteditable` question composer
  - 🚀 Launch button + Multi-select checkbox + correct count
  - `— or —` horizontal divider
  - 🤖 Generate button + "from last N min" selector
  - AI preview area below generate
- **Word Cloud tab (inactive):** Single large "☁ Open Word Cloud" button
- **Word Cloud tab (active):**
  - "✕ Close Word Cloud" button
  - Text input for host to submit words
  - Scrollable fixed-height div showing host's submitted words, newest on top
- **Status badges** pinned to bottom: Server · Agent · last seen timestamp

### Center Column

State-driven display:

- `current_activity === "none"` → large QR code (idle state, always useful)
- `current_activity === "poll"` → existing poll results panel:
  - Top bar: question title + action buttons grouped: `Close voting` + auto-close timers (5s/10s/15s/20s) + `✕ Remove` at far right
  - Vote bars below
- `current_activity === "wordcloud"` → live D3-cloud word cloud filling the panel

### Right Column

- Participant list with scores (scrollable, never hidden)
- Bottom bar: join URL + small QR icon (click → fullscreen overlay) + ↺ Reset scores

---

## Backend Changes

### `state.py` — ActivityType enum + new fields

```python
from enum import Enum

class ActivityType(str, Enum):
    NONE = "none"
    POLL = "poll"
    WORDCLOUD = "wordcloud"
```

New `AppState` fields:
```python
current_activity: ActivityType = ActivityType.NONE
wordcloud_words: dict[str, int] = {}   # normalized_word → submission count
```

`poll_active` (voting open/closed within a poll) is **retained** — it controls whether voting is open, independent of `current_activity`. The two concepts are:
- `current_activity == POLL` → poll is the visible activity
- `poll_active == True` → voting is currently open within that poll

### `routers/wordcloud.py` — new router

**`POST /api/wordcloud/status`** (Basic Auth protected)
- Body: `{"active": true|false}`
- `active=true`: sets `current_activity = WORDCLOUD`, clears `wordcloud_words`, broadcasts state
- `active=false`: sets `current_activity = NONE`, broadcasts state (client triggers PNG download)
- Returns 409 if `active=true` and `current_activity != NONE` — this means both an open poll **and** a closed-but-still-displayed poll (`current_activity == POLL`, `poll_active == False`) block opening a word cloud. The host must explicitly remove the poll first. This is intentional.

### `routers/poll.py` — mutual exclusivity

- `POST /api/poll` (create poll): returns 409 if `current_activity != NONE`
- On poll create: sets `current_activity = POLL`
- On poll delete (`DELETE /api/poll`): sets `current_activity = NONE`
- `POST /api/poll/status` (close/reopen voting): only changes `poll_active`, does **not** change `current_activity`. Closing voting does not end the poll activity.

### `routers/ws.py` — new message type

New inbound WS message:
```json
{"type": "wordcloud_word", "word": "microservices"}
```

Processing:
1. Reject if `current_activity != WORDCLOUD`
2. Normalize: `word.strip().lower()`
3. Skip if empty after normalization
4. Increment `wordcloud_words[word]`
5. Award 200 points only if sender name is **not** `"__host__"`. The host connects via `/ws/__host__` and is stored in `state.participants["__host__"]`, so an explicit name check is needed to exclude the host from scoring.
6. Broadcast state to all

### WS message type naming

Existing message types `"vote"` and `"multi_vote"` are **not renamed** in this spec. Renaming them is out of scope here — it would be a breaking change requiring coordinated frontend/backend updates and offers no benefit to the word cloud feature. Deferred to a future cleanup task.

### State message additions

`current_activity` and `wordcloud_words` are **always present** in every state broadcast, regardless of what is active. This lets frontend code unconditionally read `state.current_activity` without null guards.

Example when word cloud is active:
```json
{
  "current_activity": "wordcloud",
  "wordcloud_words": {"microservices": 4, "clean code": 2, "complexity": 1}
}
```

Example when idle:
```json
{
  "current_activity": "none",
  "wordcloud_words": {}
}
```

**Known limitation:** Per-participant word history (the "my words" list) is stored only in the participant's browser. On reconnect, the list is empty — the server does not track which participant submitted which words. This is acceptable for a live-event tool.

---

## Participant UI

### Word Cloud screen (when `current_activity === "wordcloud"`)

**Desktop layout (side-by-side):**
```
┌─────────────────────┬─────────────────────────┐
│ "Enter words that   │                         │
│  come to mind"      │   Live word cloud        │
│ [_____________] Go  │   (D3-cloud, all words)  │
│                     │                         │
│ My words:           │                         │
│ • complexity        │                         │
│ • microservices     │                         │
└─────────────────────┴─────────────────────────┘
```

**Mobile layout (stacked):**
```
┌─────────────────────────┐
│  Live word cloud        │  ← always at top, always visible
│  (full width, D3-cloud) │
├─────────────────────────┤
│ [_____________] Go      │  ← input
├─────────────────────────┤
│ My words (newest first):│
│ • complexity            │
│ • microservices         │
└─────────────────────────┘
```

**Interaction:**
- Submit with Enter key or Go button
- Input clears after submit
- Submitted word animates into "My words" list (newest on top, like falling)
- Participants only see their own words in the list — contrast with full group cloud
- Word cloud re-renders live as `wordcloud_words` updates arrive via WS state broadcast

### Points feedback
- 200 pts awarded per word submitted (participant only, not host)
- Score update arrives in next WS state broadcast — existing score display handles it

---

## Word Cloud Rendering (D3-cloud)

**Library:** `d3-cloud` loaded via CDN:
```html
<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/d3-cloud@1/build/d3.layout.cloud.js"></script>
```

**Rendering:**
- Canvas-based rendering inside a `<canvas>` element
- Word size proportional to count (min font ~14px, max font ~60px)
- Random rotation: 0° or 90° only (readable, not chaotic)
- Color: random from a fixed palette matching the dark theme
- Re-renders on every state update (debounced ~300ms to avoid thrashing)

**PNG download (host only):**
- When host closes word cloud (`current_activity` transitions from `WORDCLOUD` to `NONE`)
- Host browser captures canvas: `canvas.toBlob()` → triggers `<a download>` click
- Filename: `wordcloud-<ISO date>.png`
- Happens client-side, no server involvement

**On close — participant screens:**
- When `current_activity` returns to `"none"` in the state broadcast, participant screens return to the idle waiting screen. No download, no animation — same transition as removing a poll.

**Word Cloud tab — blocked state:**
- When `current_activity === "poll"` (a poll is active), the Word Cloud tab's Open button is **disabled and visually grayed out**. A tooltip or small label explains: "Remove the current poll first."

**`build_state_message()` in `messaging.py`:**
- Add `current_activity` and `wordcloud_words` to the state dict returned by this function so they are included in every broadcast.

---

## Testing

### `test_main.py` (API/unit tests)

- Open word cloud sets `current_activity = WORDCLOUD`
- Close word cloud sets `current_activity = NONE`
- Submit word increments `wordcloud_words` count
- Submit word awards 200 pts to participant
- Submit word by host awards 0 pts
- Word normalization: `"  Microservices  "` → `"microservices"`
- Duplicate word increments count (not deduplicated)
- Submit word rejected when `current_activity != WORDCLOUD`
- Cannot open word cloud when poll is active (409)
- Cannot create poll when word cloud is active (409)

### `test_e2e.py` (Playwright)

- Host opens word cloud → participant sees word cloud screen
- Participant A submits word → participant B's state contains that word
- Host submits word → appears in cloud but host gets no points
- Participant submits word → gets 200 points
- Host closes word cloud → `current_activity` returns to `none` on all clients
- PNG download triggered on host browser when word cloud closes
- Poll tab and word cloud are mutually exclusive (one blocks the other)

---

## Out of Scope (v2)

- Autocomplete from other participants' words
- LLM typo correction
- Configurable point value
- Custom host prompt
- Filtering/moderation of submitted words
