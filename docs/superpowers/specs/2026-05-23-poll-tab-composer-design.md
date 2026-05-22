# Poll Tab — Composer UI + Draft-Sync Backend

**Date:** 2026-05-23
**Status:** Design approved, ready for implementation plan.
**Scope:** Host-only. Participant rendering and live results are explicit follow-ups.

---

## 1. Goal

The host UI has a `Poll` tab that today is an empty placeholder (`#tab-content-poll`). This change fills in the host-side composer so a trainer can build a poll question with N options, live-sync the draft to the daemon, start the poll, and clear it. Participants do not yet render or vote on polls; that work lands in a follow-up.

A "poll" differs from the existing "quiz" feature in that it has no correct answer — it is a live audience-opinion instrument. The data shape is therefore simpler: `{question, options, multi}` with no `correct_indices` or `correct_count`.

---

## 2. Host UI

### 2.1 Left pane (`#tab-content-poll`)

Vertical stack, top → bottom:

1. **Question textarea**
   - `<textarea>`, 100% width, initial height = 2 rows of text.
   - Auto-grows on input so its content always fits without a vertical scrollbar (`el.style.height = 'auto'; el.style.height = el.scrollHeight + 'px'` on every `input`).
   - Placeholder: `"Question…"`.

2. **Start row** (right-aligned button)
   - `<button class="btn btn-success">Start</button>`.
   - Styled like the Quiz tab's `#create-btn`.
   - **Disabled** unless the question text is non-empty (after trim) AND the center pane has at least 2 options whose text is non-empty (after trim).

3. **Multi row** (left-aligned checkbox)
   - `<label><input type="checkbox" id="poll-multi"> Multi</label>`.
   - Default: unchecked.

4. **Quick Questions row**
   - Label `Quick Questions` followed by four buttons. Each button, when clicked:
     - Replaces the question textarea content with empty string (clears it).
     - Replaces the option array with the preset's options.
     - Sets the `Multi` checkbox per the preset.
     - Triggers re-render of the center pane and immediate `/poll/update` (no debounce).

   | Button label   | Options                                                  | Multi |
   |----------------|----------------------------------------------------------|-------|
   | Yes / No       | `Yes`, `No`                                              | off   |
   | True / False   | `True`, `False`                                          | off   |
   | 1–5 rating     | `1`, `2`, `3`, `4`, `5`                                  | off   |
   | Energy Level   | `🔥 On fire`, `😄 Energized`, `😐 OK`, `😴 Sleepy`, `💀 Need coffee` | off   |

### 2.2 Center pane (`#center-poll`)

A new center panel parallel to `#center-quiz`, shown when the active tab is `poll`.

Top-level structure:

- A vertical scroll container holding **option rows**.
- A red **Clear All** button below the last row, left-aligned.

#### Option rows

- One input per option. Spans 100% of center pane width.
- Implemented as a `<textarea>` (rather than `<input type="text">`) so it can auto-grow vertically when text wraps to multiple lines. Same auto-grow technique as the question textarea.
- Filled rows (non-empty after trim) get a bright contrast border: `border-color: var(--success)`.
- The trailing draft row (always empty by invariant) gets the dim default border: `border-color: var(--border)`.

#### Auto-spawn invariant

**At all times the last row is empty.** When the user types the first character into the empty trailing row, a new empty row is appended below it.

#### Middle empty rows

If the user deletes all text from a row that is not the last row, the row is kept in place (it does not auto-collapse). On `/poll/update` and `/poll/start` payloads, only non-empty options (after trim) are sent — middle-empty rows are filtered out, and the trailing draft row is always excluded.

#### Clear All button

- Red, left-aligned, below the option list.
- On click:
  1. Cancel any pending debounced `/poll/update`.
  2. Reset local UI: clear question textarea, reset options to a single empty row, uncheck Multi.
  3. POST `/api/{sid}/host/poll/stop` (empty body).

#### Overflow

If the option list grows taller than the available center-pane height, the option container scrolls vertically.

---

## 3. Backend lifecycle

Three endpoints, all on the host router (called directly on the daemon at `localhost:8081` from the host browser, per the established host-direct pattern).

### 3.1 Endpoint table

| Trigger (client)                                    | Endpoint                                              | Body                                  | Response |
|-----------------------------------------------------|-------------------------------------------------------|---------------------------------------|----------|
| Typing in question / any option (debounced 300ms)   | `PUT /api/{session_id}/host/poll/update`              | `{question: str, options: list[str], multi: bool}` | `204`    |
| Multi toggle / Quick preset / row add+remove        | `PUT /api/{session_id}/host/poll/update` (immediate)  | same                                  | `204`    |
| Click **Start** (after flushing pending update)     | `POST /api/{session_id}/host/poll/start`              | empty                                 | `204` or `409` |
| Click **Clear All** (after cancelling pending)      | `POST /api/{session_id}/host/poll/stop`               | empty                                 | `204`    |

### 3.2 Pydantic models (`daemon/poll/router.py`)

```python
class PollData(BaseModel):
    question: str
    options: list[str]
    multi: bool
```

### 3.3 Daemon state (`daemon/poll/state.py`)

```python
class PollState:
    data: PollData | None = None  # latest draft pushed by /poll/update
    started: bool = False         # flipped True by /poll/start, False by /poll/stop

poll_state = PollState()
```

Module-level singleton, same pattern as `quiz_state`.

### 3.4 Endpoint semantics

- **`PUT /poll/update`**
  - Accepts any `PollData` shape that satisfies Pydantic (no business-rule validation; the draft may be incomplete — e.g., `question=""`, `options=["Yes"]`).
  - Stores the payload as `poll_state.data`. Does not modify `started`.
  - Logged at DEBUG (high-frequency, normal-op).
  - Returns `204`.

- **`POST /poll/start`**
  - Empty body.
  - Validates `poll_state.data is not None`, `data.question.strip() != ""`, and at least 2 non-empty options after trim. On failure, returns `409 {"error": "..."}`.
  - On success: sets `poll_state.started = True`. Logged at INFO with the poll question.
  - Idempotent: clicking Start when `started == True` re-validates and returns `204` (no-op semantically).
  - Returns `204`.

- **`POST /poll/stop`**
  - Empty body.
  - Sets `poll_state.data = None`, `poll_state.started = False`. Logged at INFO.
  - Idempotent: calling when already cleared returns `204`.
  - Returns `204`.

### 3.5 Router registration

- New file `daemon/poll/__init__.py` (empty).
- New file `daemon/poll/router.py` exporting `host_router`.
- New file `daemon/poll/state.py` defining `poll_state`.
- `daemon/host_server.py` imports `host_router as poll_host_router` and calls `app.include_router(poll_host_router)` next to the existing `quiz_host_router` line.

### 3.6 Contract regeneration

- `docs/openapi.yaml` regenerated to include the three new endpoints.
- `API.md` regenerated via `python3 scripts/generate_apis_md.py --output API.md` (also enforced by pre-commit).

---

## 4. Client-side state model

In `static/host.js`, encapsulated as a module-local closure mirroring the Quiz composer pattern.

```js
const pollState = {
  question: '',
  options: [''],          // always ends with an empty draft row
  multi: false,
};
```

### 4.1 Render

`renderPoll()` rebuilds the center-pane option list from `pollState.options`, applying the bright/dim border class based on whether each row's text (trimmed) is empty.

### 4.2 Mutations

- **Question input** → update `pollState.question`, debounce 300ms → `pushUpdate()`.
- **Option input** → update `pollState.options[i]`. If `i === options.length - 1` and the new value is non-empty, push a new empty `''` to the array and re-render. Debounce 300ms → `pushUpdate()`.
- **Multi toggle** → update `pollState.multi`, immediate `pushUpdate()`.
- **Quick preset** → replace `pollState.question`, `pollState.options` (with trailing empty), `pollState.multi`. Re-render. Immediate `pushUpdate()`.
- **Clear All** → cancel any pending debounce, reset state, re-render, immediate POST `/poll/stop`.
- **Start click** → flush pending debounce (call `pushUpdate()` synchronously), then POST `/poll/start`.

### 4.3 `pushUpdate()` payload

```js
{
  question: pollState.question,
  options: pollState.options.map(s => s.trim()).filter(s => s !== ''),
  multi: pollState.multi,
}
```

(Trailing draft row and middle-empty rows are excluded.)

### 4.4 Validation for Start-button disabled state

```js
const validQuestion = pollState.question.trim() !== '';
const nonEmptyCount = pollState.options.filter(s => s.trim() !== '').length;
startBtn.disabled = !(validQuestion && nonEmptyCount >= 2);
```

### 4.5 Tab switching

In `switchTab('poll')`:
- Show `#tab-content-poll` in the left column.
- Show `#center-poll` in the center column (hide other center panels as switchTab already does).
- On first switch in a session, ensure the composer is rendered (lazy init OK).

---

## 5. Files touched

| File | Change |
|---|---|
| `static/host.html` | Fill `#tab-content-poll` with the left-pane structure (textarea, Start row, Multi row, Quick Questions row). Add a new `#center-poll` panel parallel to `#center-quiz` containing the options container and Clear All button. |
| `static/host.js` | New poll composer IIFE/module — state, render, debounce, lifecycle handlers, switchTab wiring. |
| `static/host.css` | New rules for poll question textarea, option rows (bright/dim border variants), Quick Questions button row, Clear All button placement, center-poll layout + overflow scroll. |
| `daemon/poll/__init__.py` | New, empty. |
| `daemon/poll/state.py` | New — `PollData`, `PollState`, `poll_state` singleton. |
| `daemon/poll/router.py` | New — host router with `PUT /update`, `POST /start`, `POST /stop`. |
| `daemon/host_server.py` | Register `poll_host_router` alongside `quiz_host_router`. |
| `docs/openapi.yaml` | Regenerated. |
| `API.md` | Regenerated (pre-commit enforces). |

---

## 6. Out of scope (explicit)

The following are deferred to follow-up changes and must not be added in this slice:

- Participant-side Poll rendering on `participant.html`.
- WebSocket broadcast messages (`PollOpenedMsg`, `PollVoteMsg`, `PollEndedMsg`, etc.) to participants or host.
- Live results visualization in the center pane (tally bars, percentages).
- Vote collection endpoint (`POST /api/participant/poll/vote`).
- Activity-state integration (`participant_state.current_activity = "poll"`) — touching this without participant rendering would hide the QR/idle screen for no benefit.
- Score wiring (polls have no correct answer; scoring may never apply).
- Persistence of poll data across daemon restarts.

---

## 7. Testing

Manual smoke-test in host browser at `http://localhost:8081/`:

1. Open Poll tab → verify left pane shows question textarea, Multi checkbox, Quick Questions buttons; center pane shows one empty option row + Clear All button.
2. Type in option row 1 → verify a new empty row spawns below; verify row 1 border turns bright.
3. Type into the new last row → another empty row spawns.
4. Delete all text from a middle row → row stays in place with dim border.
5. Enter a question and ensure ≥2 options have text → Start button enables.
6. Toggle Multi on and off → verify `/poll/update` fires immediately (check daemon log).
7. Click each Quick Question preset → verify question clears, options replace, Multi state matches, immediate `/poll/update` fires.
8. Click Start → verify `POST /poll/start` returns 204, form stays populated, log shows INFO "poll started".
9. Click Start with invalid state (e.g., only 1 option) — verify button is disabled (not callable).
10. Click Clear All → verify form resets to one empty option, Multi unchecked, question empty; verify `POST /poll/stop` fires.

Automated tests:
- Daemon REST contract snapshot test will pick up the three new endpoints and require an update to the snapshot — expected.
- No new unit tests required for this slice; logic is thin (state mutations + endpoint stubs). The full unit/integration test pass will land with the participant-view follow-up.

---

## 8. Open questions / deviations to flag on review

- **Question-required rule (added).** The user's spec stated only that Start should be enabled when there are ≥2 non-empty options. This spec also requires a non-empty question text for both Start-button enable and `/poll/start` server-side validation. Rationale: a poll without a question is meaningless, and an empty-question Start would otherwise hit a 409 on the server. If the user disagrees, drop the rule from both the client validator and `/poll/start`'s server-side check (Pydantic shape validation would still accept empty strings).
