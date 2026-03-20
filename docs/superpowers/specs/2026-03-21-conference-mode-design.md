# Conference Mode — Design Spec

## Problem

The tool currently targets workshops (20–30 participants, full-day sessions). For conference talks (100–350 participants, 40–60 minutes), the experience needs to be lighter: no name setup, no scores, no notifications — just instant emoji reactions and on-demand activities.

## Solution

A server-side mode flag (`workshop` / `conference`) toggled from the host panel. The mode propagates to all connected participants via WebSocket, changing both the host UI layout and the participant experience.

---

## 1. Server State

Add `mode: str` to `AppState`, defaulting to `"workshop"`.

```python
class AppState:
    mode: str = "workshop"  # "workshop" | "conference"
```

The mode is included in every `state` broadcast to participants and host. Switching mode mid-session resets scores (but this scenario is not expected in practice).

## 2. Host Panel Changes

### 2.1 Mode Toggle Badge

A new clickable badge in the status bar: `🎓` (workshop, purple) / `🎤` (conference, red). Click toggles the mode. No text label — icon only, with tooltip on hover.

Toggle calls `POST /api/mode` (host-auth protected) which updates `AppState.mode` and triggers a full broadcast.

### 2.2 Badge Compaction (both modes)

Existing badges become icon-only to save horizontal space:

| Current | Compact |
|---------|---------|
| `Server` | `🟢` (green when connected, red when disconnected) |
| `Agent` | `🤖` |
| `.txt` | `📝` |
| `Lessons` | `🧠` |
| `💬 N` | unchanged |
| `❤️` | unchanged |
| `$0.00` | unchanged |

All badges retain their existing tooltip text for discoverability.

### 2.3 Conference Mode Layout

- **Right column** (participant list, join link, QR, map, reset scores) hidden entirely
- **QR code** shown permanently in the lower half of the left column, below the tab controls
- **Participant count** (`👥 N connected`) displayed in the status bar, next to the badges
- **Grid changes** from `grid-template-columns: 25% 1fr 25%` to `25% 1fr` (2 columns)

### 2.4 Tab Order Change (both modes)

Move Debate tab to last position: Poll, Words, Q&A, Code, Debate.

## 3. Participant Changes

### 3.1 Conference Mode Landing

When `state.mode === "conference"`, the participant page shows:

- **No name bar** (no name suggestion, no edit, no avatar)
- **No score display**
- **No location prompt**
- **No notification prompt**
- **No onboarding checklist**
- **Emoji reaction grid** as main content: 3x3 grid of large, tappable emoji buttons

### 3.2 Conference Emoji Set

9 emojis in a 3x3 grid (different from workshop's 7):

```
❤️  🔥  👏
😂  🤯  💡
👍  🤔  💪
```

These replace the small bottom bar used in workshop mode. Tapping sends emoji to the overlay (same mechanism as today).

### 3.3 Activity Override

When the host launches an activity (poll, word cloud, Q&A, code review), the emoji grid is replaced by the activity UI (full screen on mobile). When the activity ends/closes, the emoji grid returns.

Debate activities are not available in conference mode.

### 3.4 UUID Identity

Participants still get a UUID (same mechanism). No name is assigned or prompted. The `set_name` WebSocket message is skipped in conference mode. Server assigns a default anonymous identifier internally.

## 4. WebSocket Protocol Changes

### 4.1 State Broadcast

The `state` message includes a new field:

```json
{
  "type": "state",
  "mode": "conference",
  ...
}
```

### 4.2 Omitted Fields in Conference Mode

In conference mode, the following fields are omitted or empty in participant broadcasts:
- `my_score` — always 0
- `my_avatar` — empty string
- Participant names not sent to other participants

### 4.3 New Endpoint

```
POST /api/mode   { "mode": "conference" | "workshop" }
```

Host-auth protected. Updates `AppState.mode`, triggers full broadcast.

## 5. What Does NOT Change

- Poll, word cloud, Q&A, code review mechanics — identical
- Emoji reaction forwarding to overlay — identical
- Backend scoring engine — still runs (for future leaderboard, issue #49)
- Status badges (Server, Agent, Transcript, etc.) — still displayed
- Host WebSocket connection — unchanged
- Overlay WebSocket connection — unchanged

## 6. Out of Scope

- **Kahoot-style leaderboard** (top 5-7, on demand) — tracked as GitHub issue #49
- **Configurable emoji set** — hardcoded for now, future enhancement
- **Separate URL/QR for conference** — mode is toggled from host, not URL-based

## 7. Files Impacted

| File | Changes |
|------|---------|
| `state.py` | Add `mode` field to `AppState` |
| `main.py` | Add `POST /api/mode` endpoint |
| `messaging.py` | Include `mode` in broadcasts, conditional field omission |
| `static/host.html` | Badge compaction, mode toggle, QR in left column, tab reorder |
| `static/host.js` | Toggle handler, conditional layout (hide right column, show QR left) |
| `static/host.css` | 2-column grid for conference, badge compact styles |
| `static/participant.html` | Conference emoji grid markup |
| `static/participant.js` | Mode-conditional rendering (name bar, score, emoji grid, notifications) |
| `static/participant.css` | Emoji grid styles |
| `routers/ws.py` | Skip `set_name` requirement in conference mode |
