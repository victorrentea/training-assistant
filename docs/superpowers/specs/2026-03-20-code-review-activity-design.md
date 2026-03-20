# Code Review Activity — Design Spec

A new interactive activity where the host pushes a code snippet to all participants. Participants independently flag lines they think contain issues. The host sees a live heatmap, then confirms lines one by one during a review phase — awarding points and sparking discussion.

## User Flow

### Phase 1: Create

1. Host navigates to a new **Code Review** tab in the host panel.
2. Host pastes a short code snippet (10–20 lines) into a text area.
3. Host optionally overrides the auto-detected programming language via a dropdown.
4. Host clicks **Start Code Review**.
5. Backend creates the code review, sets `current_activity = CODEREVIEW`, phase = `selecting`.
6. All participants see the snippet with syntax highlighting (read-only).

### Phase 2: Selecting (blind mode)

1. Participants click full rows to toggle line selections. Selected lines highlight blue with a ● marker.
2. Participants see only their own selections — no visibility of what others picked.
3. Host sees a live heatmap: line backgrounds go from transparent to red based on how many participants selected each line. Selection counts shown on the right.
4. Host has a side panel (right of the code view) that is initially empty — "Click a line to see details."
5. Host clicks **Close Selection** when ready to move on.

### Phase 3: Reviewing (host-driven reveal)

1. Selection is closed. Participants can no longer click lines.
2. Participants now see **percentage badges** on the right of each line — showing what % of all participants selected that line. They also still see their own selections (dimmed blue).
3. Host clicks a line in the code view to inspect it:
   - The side panel shows the list of participants who selected that line, **sorted ascending by score** (lowest first, so the host can call on less-active participants).
   - A **Confirm Line** button appears at the bottom of the side panel.
4. Host clicks **Confirm Line**:
   - 200 points awarded to every participant who selected that line.
   - The line turns green (with ✓) on both host and participant screens.
   - Participants who selected it see "+200 pts" next to the line.
5. Host can confirm multiple lines, one at a time.
6. Lines the host does not confirm get no points (no penalty either).
7. Host clicks **Clear Code Review** when done.

## Activity Type

Add `CODEREVIEW = "codereview"` to the `ActivityType` enum in `state.py`.

## State Model

New fields in `AppState`:

```python
codereview_snippet: str | None = None          # raw code text
codereview_language: str | None = None          # detected or overridden language
codereview_phase: str = "idle"                  # "idle" | "selecting" | "reviewing"
codereview_selections: dict[str, set[int]] = {} # uuid → set of selected line numbers
codereview_confirmed: set[int] = set()          # lines the host confirmed as correct
```

Phase states:
- `idle` — no code review running
- `selecting` — participants clicking lines, host sees heatmap
- `reviewing` — selection closed, host confirms lines one by one

## REST Endpoints

New router: `routers/codereview.py`. All endpoints require host auth.

| Method | Endpoint | Body | Effect |
|--------|----------|------|--------|
| POST | `/api/codereview` | `{snippet: str, language?: str}` | Create code review. If `language` is omitted, store `null` — frontend auto-detects via highlight.js. Set phase to `selecting`, `current_activity = CODEREVIEW`. Broadcast state. |
| PUT | `/api/codereview/status` | `{open: bool}` | `open=false` → phase `reviewing`. `open=true` is a no-op (re-opening selection is not supported). Broadcast state. |
| PUT | `/api/codereview/confirm-line` | `{line: int}` | Confirm a line. Award 200 pts to each participant who selected it. Add to `confirmed_lines`. Broadcast state. |
| DELETE | `/api/codereview` | — | Clear all code review state. Set `current_activity = NONE`, phase to `idle`. Broadcast state. |

## WebSocket Messages

### Participant → Server

| Message type | Phase | Fields | Effect |
|-------------|-------|--------|--------|
| `codereview_select` | selecting | `line: int` | Add line number to participant's selection set |
| `codereview_deselect` | selecting | `line: int` | Remove line number from participant's selection set |

Validation: reject if `current_activity != CODEREVIEW` or `codereview_phase != "selecting"`. Reject invalid line numbers (< 1 or > total lines).

### Server → Participant (in `broadcast_state`)

```json
{
  "type": "state",
  "current_activity": "codereview",
  "codereview": {
    "snippet": "public String process(...) { ... }",
    "language": "java",
    "phase": "selecting",
    "my_selections": [2, 4],
    "confirmed_lines": [],
    "line_percentages": {}
  }
}
```

- `my_selections`: always present, shows the participant's own picks.
- `confirmed_lines`: lines the host has confirmed (green on participant screen).
- `line_percentages`: **only populated during `reviewing` phase**. Map of `line_number → percentage` for every line that got at least one selection. Keys are 1-based line numbers as strings; values are integers 0–100. Example: `{"2": 44, "4": 69, "7": 88}`.

### Server → Host (in `broadcast_state`)

```json
{
  "type": "state",
  "current_activity": "codereview",
  "codereview": {
    "snippet": "public String process(...) { ... }",
    "language": "java",
    "phase": "selecting",
    "line_counts": {"2": 18, "4": 27, "7": 28},
    "confirmed_lines": [4],
    "line_participants": {
      "4": [
        {"uuid": "abc", "name": "Alex", "score": 120},
        {"uuid": "def", "name": "Jamie", "score": 340}
      ]
    }
  }
}
```

- `line_counts`: always present for the host — powers the heatmap. Keys are 1-based line numbers as strings; values are integer counts.
- `confirmed_lines`: lines already confirmed.
- `line_participants`: full participant breakdown for **all lines** (host needs to click any line to see the list). Sorted ascending by score.

## Scoring

- **During selecting phase**: no points awarded.
- **On host confirm**: 200 points (flat) per confirmed line, awarded to every participant who selected it.
- No penalty for selecting a line that the host does not confirm.
- No speed-based bonus — this is about discussion, not racing.

## Syntax Highlighting

Use **highlight.js** (CDN, single JS + CSS file). No build step needed.

- Auto-detect language on the frontend when rendering the snippet.
- Host can override via a dropdown (`Auto-detect`, `Java`, `Python`, `JavaScript`, `TypeScript`, `SQL`, `Go`, `C#`, `Kotlin`, `Bash`).
- The selected/overridden language is stored in `codereview_language` and sent to all clients.
- highlight.js handles the syntax coloring; line selection is a custom overlay on top.

## Host UI

### Code Review Tab

A new tab in the host panel, alongside Poll, Word Cloud, Q&A.

**Create state**: text area for pasting code, language dropdown (default: "Auto-detect"), "Start Code Review" button.

**Selecting state**: two-pane layout:
- **Left pane**: code snippet with heatmap overlay (line backgrounds go transparent → red based on selection count). Selection counts shown on the right of each line.
- **Right pane (side panel)**: initially empty ("Click a line to see details"). When host clicks a line, shows the participant list for that line sorted ascending by score.
- **Bottom bar**: participant count + "Close Selection" button.

**Reviewing state**: same two-pane layout, but:
- Already-confirmed lines show green with ✓.
- Host clicks unconfirmed lines → side panel shows participant list + "Confirm Line" button.
- Bottom bar: confirmed line count + "Clear Code Review" button.

## Participant UI

### Selecting Phase

- Full-width code view with syntax highlighting.
- Each line is clickable (full row). Hover effect on unselected lines.
- Selected lines: blue highlight with ● marker in the gutter.
- Click again to deselect (toggle).
- Counter at bottom: "You selected N lines".
- No visibility of others' selections.

### Reviewing Phase

- Lines are no longer clickable.
- Own selections shown as dimmed blue with ● marker.
- Confirmed lines (that participant also selected): green with ✓ and "+200 pts" badge.
- Confirmed lines (that participant did NOT select): green with ✓ (no points badge).
- Percentage badges on the right of every line that had selections: `44%`, `69%`, etc.
- Score summary at bottom showing total points earned from this activity.

## File Changes

| File | Change |
|------|--------|
| `state.py` | Add `CODEREVIEW` to `ActivityType`, add code review fields to `AppState` |
| `routers/codereview.py` | New file — REST endpoints for create, status, confirm-line, clear |
| `routers/ws.py` | Handle `codereview_select` and `codereview_deselect` messages |
| `messaging.py` | Add code review data to `build_participant_state()` and `build_host_state()` |
| `main.py` | Register codereview router |
| `static/host.html` | Add Code Review tab and UI structure |
| `static/host.js` | Add code review rendering, heatmap, side panel, confirm flow |
| `static/host.css` | Code review styles (heatmap, side panel) |
| `static/participant.html` | Add highlight.js CDN links |
| `static/participant.js` | Add code review screen rendering, line selection, review phase |
| `static/participant.css` | Code review styles (line selection, percentages) |

## Dependencies

- **highlight.js**: loaded from CDN in both `host.html` and `participant.html`. No npm install, no build step. Adds ~40KB gzipped for core + common languages.

## Future Enhancement

- [GitHub Issue #23](https://github.com/victorrentea/training-assistant/issues/23): Smart paste — use Claude API to auto-extract code from LLM responses.
