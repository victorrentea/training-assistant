# Kahoot-Style Leaderboard — Design Spec

**Issue:** [#49](https://github.com/victorrentea/training-assistant/issues/49)
**Date:** 2026-03-21

---

## Overview

Add a Kahoot-style dramatic leaderboard reveal, triggered on demand by the host. Works in both conference and workshop modes. In conference mode, participants get auto-assigned names from a pool of movie/game characters.

---

## 1. Auto-Assigned Names in Conference Mode

### Name Pool
- 300+ entries stored as `(name, universe)` tuples in a new `names.py` module.
- Universes: Star Wars, LOTR, Matrix, Marvel, Star Trek, Back to the Future, Blade Runner, Hitchhiker's Guide, Harry Potter, Dune, etc.
- Examples: `("Yoda", "Star Wars")`, `("Neo", "Matrix")`, `("Gandalf", "LOTR")`

### Name Storage
- Names stored as **two separate fields** internally:
  - `state.participant_names[uuid]` = `"Yoda"` (character name only)
  - New field: `state.participant_universes[uuid]` = `"Star Wars"`
- Display format when combined: `"Yoda (Star Wars)"`

### Assignment
- On first WS connection in conference mode, server picks a random **unused** name from the pool. This **replaces** the existing empty-string assignment in `ws.py` line 86.
- Assigned to `participant_names[uuid]` and `participant_universes[uuid]`.
- Fallback if pool exhausted: `"Hero-{short_uuid}"` with universe `""`.
- **Name recycling**: Names from disconnected participants (removed from `state.participants`) are eligible for reuse. The "unused" check looks at currently connected UUIDs only.

### Letter Avatar
- First **two letters** of the character name in uppercase (e.g., `"YO"` for Yoda, `"NE"` for Neo).
- Rendered as a colored circle with the 2-letter text.
- Color computed from hash of `name + universe` — deterministic, visually distinct.
- Stored in `state.participant_avatars[uuid]` as `"letter:YO:#a855f7"` format.
- **Frontend detection**: Avatar renderer checks if value starts with `"letter:"` → render colored circle. Otherwise → render image as before.

### Optional Rename
- Small edit icon in participant top status bar (not prompted, not prominent).
- If they rename, letter avatar updates to reflect the new name's first 2 letters.
- Color recomputed from new name (universe cleared to `""`).

### Host Visibility
- Conference mode: participant list (right column) stays hidden. Host sees only participant count.
- Auto-assigned names are invisible to participants until leaderboard reveal.

---

## 2. Leaderboard Trigger and Server Logic

### Host Button
- "Leaderboard" button with trophy icon placed in the **tab bar** alongside Poll, Words, Q&A, Code, Debate.
- Styled as a **button, not a tab** — clicking does not switch tab content.
- Toggles leaderboard on/off.
- **Disabled** when fewer than 5 participants have `score > 0`.

### REST Endpoints (host-auth protected)
- `POST /api/leaderboard/show` — activates leaderboard
- `POST /api/leaderboard/hide` — deactivates leaderboard
- **Note**: Add to CLAUDE.md auth scope list after implementation.

### Server Behavior on Show
1. Set `state.leaderboard_active = True`
2. Compute top 5 by score from `state.scores` (only participants with `score > 0`)
3. **Personalized broadcast** using the same per-participant sending pattern as `broadcast_state()` — iterate over connected participants, send each their own message with personalized `your_rank` and `your_score`:

```json
{
  "type": "leaderboard",
  "entries": [
    {"rank": 1, "name": "Yoda", "universe": "Star Wars", "score": 450, "letter": "YO", "color": "#a855f7"},
    {"rank": 2, "name": "Neo", "universe": "Matrix", "score": 380, "letter": "NE", "color": "#3b82f6"}
  ],
  "total_participants": 147,
  "your_rank": 12,
  "your_score": 280
}
```

- Host receives `your_rank: null, your_score: null`.

### Late Joiners
- If `state.leaderboard_active == True` when a new participant connects, include `leaderboard` data in their initial state message (or send a separate `leaderboard` message immediately after connection).

### Server Behavior on Hide
1. Set `state.leaderboard_active = False`
2. Broadcast `{"type": "leaderboard_hide"}` to all clients (non-personalized, simple broadcast).

### Tie-Breaking
1. Higher score wins.
2. If tied: alphabetical by name.
- (Simplified from vote_times since those can be lost on reconnect.)

### Interaction with Activities
- Leaderboard can be shown while a poll/activity is active. The overlay sits on top.
- Voting and interaction continue to work underneath — the leaderboard is purely visual.

---

## 3. Host Leaderboard Display (Dramatic Reveal)

### Layout
- Full-screen **overlay** on the host center column, on top of current activity content (not replacing it).

### Animation Sequence
1. Dark overlay fades in with title: **"LEADERBOARD"**
2. Position **#5** slides in from below
3. 0.8s pause
4. Position **#4** slides in
5. 0.8s pause
6. Position **#3**, **#2** follow
7. Position **#1** appears last with extra emphasis (larger size, glow effect)

### Each Entry Shows
- Rank number (large)
- Letter avatar (colored circle with 2-letter code) — in workshop mode, use image avatar instead
- Name (Universe) — e.g., "Yoda (Star Wars)". In workshop mode: just the name.
- Score in points

### Dismiss
- Host clicks the Leaderboard button again, or a close (X) button on the overlay.

---

## 4. Participant Leaderboard View

### When `leaderboard` Message Arrives
- Overlay appears on participant's screen.
- Shows:
  - **"Your rank: #12 out of 147"** (large, prominent)
  - **"280 pts"** (their score)
  - Top 5 list below (same entries as host, smaller format)
  - If participant IS in the top 5, their entry is highlighted/glowing

### Dismiss
- Disappears automatically when host broadcasts `leaderboard_hide`.
- No manual dismiss by participant.

---

## 5. Mode Compatibility

| Aspect | Workshop Mode | Conference Mode |
|---|---|---|
| Names | Real names (user-provided) | Auto-assigned from pool |
| Avatars on leaderboard | Image avatars (LOTR/hash) | Letter avatars (2-char + color) |
| Scores visible normally | Yes | No (forced to 0) |
| Scores visible on leaderboard | Yes | Yes (only during reveal) |
| Participant list on host | Visible | Hidden |
| Leaderboard button | Visible | Visible |

---

## 6. Data Model Changes

### New AppState Fields
```python
leaderboard_active: bool = False
participant_universes: dict[str, str] = {}  # uuid → universe string
```

### New Module: `names.py`
- `CHARACTER_NAMES: list[tuple[str, str]]` — 300+ `(name, universe)` tuples
- `assign_conference_name(state) -> tuple[str, str]` — picks random unused name from pool (checking against currently connected UUIDs), returns `(name, universe)`
- `compute_letter_avatar(name: str, universe: str) -> tuple[str, str]` — returns `(letter_code, hex_color)`

### Changes to Existing Fields
- `participant_names[uuid]` — in conference mode, stores character name (e.g., `"Yoda"`) instead of empty string
- `participant_avatars[uuid]` — in conference mode, stores `"letter:YO:#a855f7"` instead of image filename

### Frontend Avatar Rendering
All avatar rendering locations in `participant.js` and `host.js` must check:
- If avatar starts with `"letter:"` → parse `letter:XX:#color` → render colored circle with text
- Otherwise → render `<img>` as before

---

## 7. New Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/leaderboard/show` | Host | Activate leaderboard, personalized broadcast to all |
| POST | `/api/leaderboard/hide` | Host | Deactivate leaderboard, broadcast to all |

---

## 8. WebSocket Messages

| Type | Direction | Payload | When |
|---|---|---|---|
| `leaderboard` | Server → Each participant (personalized) | `{entries, total_participants, your_rank, your_score}` | Host triggers show, or late joiner connects |
| `leaderboard_hide` | Server → All (broadcast) | `{}` | Host triggers hide |
