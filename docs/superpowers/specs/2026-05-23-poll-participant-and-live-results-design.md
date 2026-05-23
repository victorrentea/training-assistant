# Poll — Participant Rendering & Host Live Results — Design

**Phase 2** of the Poll feature. Phase 1 (host composer + draft-sync backend) shipped earlier and lives at `docs/superpowers/specs/2026-05-23-poll-tab-composer-design.md`.

## 1. Goal

Make the Poll feature fully live and bidirectional:

- Participants see polls open, vote on them, and (when the host enables Public) watch live counts update in real time.
- Host sees a live-results panel with auto-reordering bars, regardless of public setting.
- All state — including votes — persists across daemon restart and participant refresh, with the participant's previous selection re-highlighted.

## 2. Architecture

```
Phase 1 (already shipped):
  Host left-pane composer ──PUT /poll/update──> daemon (poll_state.data)
  Host clicks Start       ──POST /poll/start──> daemon (poll_state.started)
  Host clicks Clear       ──POST /poll/stop───> daemon (reset)

Phase 2 (this spec) adds:
  daemon poll_state         + .votes: dict[uuid → {option_indices, voted_at}]
                            + .opened_at
                            + .vote_counts() / .distinct_voter_count() / reset()

  Participant client        + #activity-poll-section
                            + WS handlers: poll_opened, poll_updated, activity_updated
                            + POST /api/participant/poll/vote
                            + state restore via /api/participant/state on (re)connect

  Host client               + #center-poll live results
                            + WS handler: poll_host_update
                            + FLIP reorder + Layout-A fill-behind-text bars

  Persistence               + PersistedPollState (mirrors PersistedQuizState)
                            + poll snapshot in _build_runtime_session_snapshot
                            + poll restore in _apply_runtime_snapshot_restore

  Hermetic test             + tests/docker/test_poll_live.py
```

**Tech:** vanilla JS (no build step), Pydantic + FastAPI on the daemon, WebSockets via existing Railway broadcast / daemon-direct host channels, Playwright for hermetic E2E.

## 3. Wire contract

### Participant channel (3 message types, 1 already exists)

```python
# existing — no change
class ActivityUpdatedMsg(BaseModel):
    type: Literal["activity_updated"] = "activity_updated"
    current_activity: str          # "poll" on Start, "none" on Clear

# new — bare signal, no payload. Pure "new session" marker.
class PollOpenedMsg(BaseModel):
    type: Literal["poll_opened"] = "poll_opened"

# new — workhorse. Fires on Start (initial snapshot), host edits, and
# participant votes when public=true.
class PollUpdatedMsg(BaseModel):
    type: Literal["poll_updated"] = "poll_updated"
    poll: PollPublicSnapshot       # {question, options, multi, public}
    counts: list[int] | None       # present iff poll.public; absent → participants hide bars
```

`PollOpenedMsg` is a bare signal because WS preserves order — the immediately-following `PollUpdatedMsg` carries the snapshot. Splitting them keeps "new session" (reset local vote state) distinct from "snapshot updated" (preserve local vote state).

### Host channel (1 new message type, via `notify_host`)

```python
class PollHostUpdateMsg(BaseModel):
    type: Literal["poll_host_update"] = "poll_host_update"
    poll: PollFullSnapshot         # same shape as PollPublicSnapshot
    counts: list[int]              # ALWAYS full counts (host sees all regardless of public)
    voted_count: int               # distinct voters
```

### Trigger table

| Event | broadcast → participants | notify_host → host |
|---|---|---|
| Host Start | `ActivityUpdatedMsg("poll")`, `PollOpenedMsg`, `PollUpdatedMsg(poll, counts_or_null)` | `ActivityUpdatedMsg("poll")`, `PollHostUpdateMsg(poll, counts=[0…], voted_count=0)` |
| Host edits Q / options / multi / public | `PollUpdatedMsg(poll, counts_or_null)` | `PollHostUpdateMsg(poll, counts, voted_count)` |
| Participant votes — poll public | `PollUpdatedMsg(poll, counts)` | `PollHostUpdateMsg(poll, counts, voted_count)` |
| Participant votes — poll private | — | `PollHostUpdateMsg(poll, counts, voted_count)` |
| Host Clear | `ActivityUpdatedMsg("none")` | `ActivityUpdatedMsg("none")` |

**No separate "cleared" message.** `ActivityUpdatedMsg("none")` is the universal tear-down signal for any activity. The participant client resets state for the old activity whenever `current_activity` changes.

### Single daemon helper (source of truth)

```python
async def _push_poll_state():
    counts = poll_state.vote_counts()
    voted  = poll_state.distinct_voter_count()
    counts_for_pax = counts if poll_state.data.public else None
    broadcast(PollUpdatedMsg(poll=_pax_snapshot(), counts=counts_for_pax))
    await notify_host(PollHostUpdateMsg(poll=_pax_snapshot(), counts=counts, voted_count=voted))
```

Called after every `cast_vote()` and after every `update_poll()`. On Start, also broadcasts `ActivityUpdatedMsg("poll")` + `PollOpenedMsg` first.

## 4. REST endpoints

### Existing — behavior extended (host-only)

| Method | Path | Change |
|---|---|---|
| `PUT  /api/{sid}/host/poll/update` | If `started`: reject option removal (409). If `multi` changed, wipe `poll_state.votes` + invalidate cache. Always call `_push_poll_state()` afterward. |
| `POST /api/{sid}/host/poll/start`  | Already validates draft. Now also: set `current_activity="poll"`, set `opened_at`, broadcast `ActivityUpdatedMsg("poll")` + `PollOpenedMsg`, call `_push_poll_state()`. |
| `POST /api/{sid}/host/poll/stop`   | `poll_state.reset()` (wipes data, started, opened_at, votes). Set `current_activity="none"`. Broadcast `ActivityUpdatedMsg("none")`. |

### New — participant vote

```
POST /api/{sid}/api/participant/poll/vote
  headers: X-Participant-ID: <uuid>
  body:    {"options": [int]}        # indices; [] = clear my vote
  returns: 204 on accept
           409 if poll not started, indices out of range, or multi=false but len>1
```

After accept, daemon calls `_push_poll_state()` which routes the update per the table above.

Reaches the daemon via the existing Railway catch-all (`participant_proxy_router` at `railway/features/ws/proxy_bridge.py:89-109`). **No new Railway route needed.**

### New — host state snapshot (initial render only)

```
GET /api/{sid}/host/poll
  returns: {poll: {…}|null, started: bool, counts: [int], voted_count: int}
```

Called once when the host activates the Poll tab / activity (parallel to existing `GET /api/{sid}/host/quiz`). Subsequent updates arrive via `PollHostUpdateMsg`.

### Existing — extended response

`GET /api/{sid}/api/participant/state` response (`ParticipantStateResponse`) gains four optional fields:

```python
poll: PollPublicSnapshot | None = None
poll_active: bool = False
my_poll_voted_indices: list[int] | None = None      # this participant only
poll_vote_counts: list[int] | None = None           # set only when poll.public
```

Server pre-filters: `my_poll_voted_indices` is built by `poll_state.votes.get(pid)` — participants never receive other users' vote data. Public mode controls only whether the aggregate `poll_vote_counts` field is included.

## 5. Daemon state

### In-memory (`daemon/poll/state.py`)

```python
@dataclass
class PollState:
    data: Optional[PollData] = None
    started: bool = False
    opened_at: Optional[str] = None
    votes: dict[str, dict] = field(default_factory=dict)
    # votes[uuid] = {"option_indices": list[int], "voted_at": "ISO"}
    _vote_counts_cache: Optional[list[int]] = None
    _vote_counts_dirty: bool = True

    def cast_vote(self, pid: str, option_indices: list[int]) -> bool: ...
    def vote_counts(self) -> list[int]: ...
    def distinct_voter_count(self) -> int: ...
    def reset(self) -> None: ...
```

`cast_vote` validates: `started=True`, indices in range, `len<=1` when not multi. Updates `votes[pid]`, invalidates cache. Empty `options=[]` removes the entry.

`vote_counts` returns a cached `list[int]` of length `len(options)`. Cache invalidated on every vote and on every `poll_state.data = …` write.

`reset` clears every field.

### Persisted model (`daemon/persisted_models.py`)

```python
class PersistedPollState(PersistedModel):
    data: PollDataPersisted | None = None
    started: bool = False
    opened_at: str | None = None
    votes: dict[str, dict] = Field(default_factory=dict)

class PersistedSessionState(PersistedModel):
    # ... existing fields ...
    quiz: PersistedQuizState | None = None
    poll: PersistedPollState | None = None       # NEW
```

`PollDataPersisted` mirrors `PollData` (question, options, multi, public). Pydantic's `extra="ignore"` (already set on `PersistedModel`) means existing prod `session-state.json` files load cleanly — no migration needed.

### Snapshot / restore (`daemon/__main__.py`)

In `_build_runtime_session_snapshot()` (near the existing `quiz` block):

```python
from daemon.poll.state import poll_state
# ...
"poll": ({
    "data": poll_state.data.model_dump() if poll_state.data else None,
    "started": poll_state.started,
    "opened_at": poll_state.opened_at,
    "votes": dict(poll_state.votes),
} if poll_state.data or poll_state.votes else None),
```

In `_apply_runtime_snapshot_restore()`:

```python
from daemon.poll.state import poll_state
poll_data = snapshot.get("poll")
if poll_data:
    if poll_data.get("data"):
        poll_state.data = PollData.model_validate(poll_data["data"])
    poll_state.started = poll_data.get("started", False)
    poll_state.opened_at = poll_data.get("opened_at")
    poll_state.votes = poll_data.get("votes") or {}
    poll_state._vote_counts_dirty = True
```

### Persistence cadence

Implicit via the existing 3-second polling loop — `cast_vote` / `update_poll` / `start_poll` / `stop_poll` mutate state in-place; `_flush_session_state_backup()` hashes the full snapshot and writes `session-state.json` atomically iff hash changed. **Worst-case loss window: 3s** — same trade-off as existing quiz votes.

### WS reconnect refresh

`_ws.onopen` in `static/participant.html` currently does NOT re-fetch `/api/participant/state` on reconnect. **Fix required as part of this spec:** after the first successful connect, every subsequent `onopen` must trigger a `/state` refetch so participants restore UI after daemon restarts.

```js
var _firstConnect = true;
_ws.onopen = function() {
  if (!_firstConnect) {
    _refetchInitialState();    // calls existing /state fetch + _applyState
  }
  _firstConnect = false;
  // ... existing toast timer
};
```

This is generic — it benefits every feature, not just poll. We make this change as part of the poll spec because it's required for the "daemon-restart → poll restored on screen" story.

## 6. Edge cases (decisions locked in)

| Case | Decision |
|---|---|
| Host removes an option while running | **Reject** with 409. Composer-side UI should grey out removal too. Only rename + append are allowed. |
| Host flips `multi` true↔false while running | **Wipe all votes.** Daemon clears `poll_state.votes`, broadcasts/notifies as usual. Participants see their selection cleared. |
| Host toggles `public` false while participants are watching counts | Daemon's next broadcast carries `counts: null` → participants render no counts. Implicit — no dedicated message. |
| Host toggles `public` true mid-poll | Daemon's next broadcast carries the current `counts` array → participants begin rendering counts. |
| Participant submits `options: []` (deselect everything in multi) | Daemon removes the participant's entry from `votes`. Counts recompute. |
| Poll has 0 votes | All bars at 0% width, no `leading` class. Options shown in original order. Header reads "N voted" where N=0. |
| Score impact | **None.** Polls have no correct answer. `ScoresUpdatedMsg` never fires for poll votes. |
| History after Clear | **None.** Clear wipes everything from memory + disk. No `past_polls` archive. |

## 7. Host live-results UI

### Layout (Layout A — fill behind option text)

```html
<div id="center-poll" class="center-panel" style="display:none;">
  <div class="poll-results-header">
    <div class="poll-results-question" id="poll-results-question">—</div>
    <div class="poll-results-meta">
      <span id="poll-results-voted">0 voted</span>
      <span class="poll-results-meta-sep">·</span>
      <span id="poll-results-mode">single-select</span>
      <span class="poll-results-meta-sep">·</span>
      <span id="poll-results-visibility">private</span>
    </div>
  </div>
  <div id="poll-results-bars" class="poll-results-bars"></div>
</div>
```

CSS reuses the existing `.bar-fill { transition: width 0.5s ease; }` pattern from `host.css`. New selectors `.poll-results-bars` / `.poll-bar-row` / `.poll-bar-row .fill` / `.poll-bar-row.leading .fill`. Full CSS in Section 4 of brainstorming notes; bake into `host.css`.

### Bar width formula

```
width = max_count > 0 ? (count / max_count) * 100% : 0%
```

Relative-to-max, not relative-to-sum — makes the ranking obvious at a glance. Leading row at 100%, others scaled down. `leading` class applied to all rows tied for `max_count` (provided `max_count > 0`).

### FLIP reorder (~300ms)

Standard FIRST-LAST-INVERT-PLAY technique using `requestAnimationFrame`. Rows reorder via DOM append in the new sort order; each row's pre-reorder position is captured, post-reorder positions measured, deltas applied as `transform: translateY(dy)px` with `transition: none`, then the next frame removes the transform and the CSS transition animates back to identity over 300ms.

Sort key: `count DESC, original_index ASC` — stable. Ties never swap. A row only moves when it strictly out-ranks the one above or falls strictly behind the one below. This matches the user's "minimum positions moved" rule.

### Host WS handler

```js
case 'poll_host_update':
  _hostPoll = msg.poll;
  _hostPollCounts = msg.counts;
  _hostPollVoted = msg.voted_count;
  renderPollResults();
  break;
```

`renderPollResults()`:
1. Updates header text + meta.
2. If options count changed, rebuilds bars DOM from scratch (added options pop in; no FLIP for that).
3. For each row, updates `.label`, `.count`, `.fill` width, toggles `.leading`.
4. Calls `reorderBars(container, sortIndices(counts))` to FLIP rows into the new sort order.

Initial render: host subscribes to `poll_host_update` via the existing host WS. On Poll tab activation, fetches `GET /api/{sid}/host/poll` once for the initial snapshot, then relies on WS pushes.

## 8. Participant rendering

### Layout

```html
<section id="activity-poll-section" style="display:none;">
  <div class="poll-card">
    <h2 id="poll-question-text">—</h2>
    <div id="poll-options" class="poll-options"></div>
    <div id="poll-status-bar" class="poll-status-bar"></div>
  </div>
</section>
```

CSS mirrors `.quiz-card` / `.option-btn` for visual consistency. Public-mode counts render as a fill bar behind the option label (Layout A consistency between host and participant). Selection state uses a stronger border + background to stand out from the count fill.

### Status bar (bottom of options list)

- Single-select, no vote yet: `"Single option"`
- Single-select, voted: `"Single option · tap another to change"`
- Multi-select, 0 selected: `"Select as many as you want"`
- Multi-select, N selected: `"Select as many as you want · N selected"`

### State vars

```js
var _pollActive = false;
var _currentPoll = null;          // {question, options, multi, public}
var _myPollVote = null;           // single: int idx | null;  multi: Set<int>
var _pollVoteCounts = null;       // list[int] when public, null otherwise
```

### Render function (`_renderActivityPoll`)

Pure render — reads state, regenerates options HTML. Options rendered in **host-typed order** (no FLIP on participant side). Selection is `.selected` class. Multi shows a checkbox icon inside the button. Counts render as right-aligned numeric + fill bar behind option text, but only when `_pollVoteCounts !== null`.

### Vote submission (`castPollVote`)

Optimistic local re-render, then POST to `/api/participant/poll/vote`. Single-select: tap same option = no-op; tap different = replace. Multi-select: tap toggles inclusion. Empty multi-vote sends `options: []`.

### WS handlers

```js
case 'poll_opened':
  _pollActive = true;
  _myPollVote = null;            // new session — PollUpdated arrives next
  _renderActivityPoll();
  break;

case 'poll_updated':
  _currentPoll = msg.poll;
  _pollVoteCounts = msg.counts !== undefined ? msg.counts : null;
  // Reconcile vote shape if multi flipped:
  if (_currentPoll.multi && !(_myPollVote instanceof Set))
    _myPollVote = _myPollVote !== null ? new Set([_myPollVote]) : new Set();
  else if (!_currentPoll.multi && _myPollVote instanceof Set)
    _myPollVote = null;          // daemon wiped server-side; follow
  _renderActivityPoll();
  break;

case 'activity_updated':
  if (_currentActivity !== msg.current_activity)
    _resetActivityState(_currentActivity);
  _currentActivity = msg.current_activity;
  _renderActivityPoll();
  break;
```

### State restore (REST `/api/participant/state`)

`_applyState(msg)` dispatches to `_applyPollState(msg)` when any poll field is present. Restores `_currentPoll`, `_pollActive`, `_myPollVote` (typed correctly based on multi), `_pollVoteCounts`.

## 9. Hermetic test

`tests/docker/test_poll_live.py`, marked `@pytest.mark.nightly` (>5s runtime, follows project convention).

### Scenario (matches user's spoken walkthrough)

1. **Setup:** Fresh session. Spin up host (with HTTP Basic Auth), one participant (Alice). All Playwright contexts pointing at the hermetic stack.
2. **Host:** Open Poll tab. Type question "How was the demo?". Add options "A" and "B". Click Start.
3. **Alice:** Receives `activity_updated("poll")` + `poll_opened` + `poll_updated`. Renders the poll. Clicks "A". Verifies "A" is selected, status bar says "Single option · tap another to change".
4. **Host:** Add a third option "C". Verify host live-results panel now shows 3 bars; Alice's screen now shows option "C" appended.
5. **Alice:** Click "B". Verify "A" becomes deselected, "B" selected. Verify daemon's `poll_state.votes[alice_uuid] == {option_indices: [1], …}`.
6. **Host:** Toggle Multi checkbox ON. Verify Alice's screen now shows checkboxes; her previous vote is **cleared** (per the wipe-on-flip rule). Status bar says "Select as many as you want".
7. **Alice:** Click "B" and "C". Verify both highlighted, status bar says "Select as many as you want · 2 selected".
8. **Host:** Toggle Public checkbox ON. Verify Alice sees counts appear: A=0, B=1, C=1. Verify host live-results bars unchanged in shape (host always saw counts).
9. **Second participant (Bob) joins.** Joins the session, lands on the activity view directly via `current_activity="poll"`. Sees the live poll with counts A=0, B=1, C=1.
10. **Bob:** Click "B". Verify counts now A=0, B=2, C=1 on **both** Alice's and Bob's screens.
11. **Host:** Verify live-results panel reorders so "B" is now at the top (was tied with C, now strictly higher; expect "C" still at position 2, "A" at position 3 — FLIP animation in real browser, but for the test just assert DOM order matches sorted order).
12. **Host:** Verify daemon's `vote_counts() == [0, 2, 1]`.
13. **Host:** Click Clear. Verify Alice and Bob both navigate back to welcome/waiting view. Verify daemon's `poll_state.data is None`, `poll_state.votes == {}`.

### Refresh sub-test (added to same file)

14. Host opens a fresh poll with 2 options, public=true. Alice votes. Daemon `session-state.json` is flushed (wait ~4s or invoke the flush directly).
15. Alice **refreshes her browser**. Verify the poll renders with her previous vote highlighted and the current counts displayed.
16. **Daemon restart** (Docker `docker restart daemon` or equivalent). After daemon recovery, Alice should see her UI restored from the WS-reconnect → `/state` refetch path.

### Page-object helpers

Add to `tests/pages/host_page.py`:
- `add_poll_option(text)` — fills the next empty draft row
- `toggle_poll_multi()` / `toggle_poll_public()`
- `start_poll()` / `clear_poll()`
- `poll_results_row(idx)` — returns DOM handle for a results row, exposes `.text`, `.count`, `.is_leading`, `.position`

Add to `tests/pages/participant_page.py`:
- `cast_poll_vote(idx)` — clicks option idx
- `poll_status_text()` / `poll_visible_counts()` / `poll_selected_indices()`

## 10. Out of scope

- Per-participant vote breakdown to the host UI (host sees aggregates only — no "who voted for what" panel).
- Cross-poll history (`past_polls` archive). Clear wipes everything.
- Score / leaderboard impact for poll votes.
- Multi-correct-answer reveal flow (polls have no correct answer by design).
- Animated reorder on the participant side (only the host live-results reorders).
- A "broadcast" / "publish to participants" intermediate step — Start immediately routes participants to the activity view.

## 11. Files touched

```
daemon/poll/state.py                 ✏️  extend with votes + helpers
daemon/poll/router.py                ✏️  participant_router (/vote), extend host endpoints
daemon/poll/persistence.py           🆕  optional helper module if needed (else inline in __main__.py)
daemon/persisted_models.py           ✏️  PersistedPollState + field on PersistedSessionState
daemon/ws_messages.py                ✏️  PollOpenedMsg, PollUpdatedMsg, PollHostUpdateMsg + register
daemon/participant/router.py         ✏️  extend ParticipantStateResponse with poll fields
daemon/__main__.py                   ✏️  poll in snapshot + restore
daemon/host_server.py                ✏️  register participant_router for poll (if not already auto-mounted)

static/host.html                     ✏️  add #center-poll results panel structure
static/host.css                      ✏️  add poll-results-* classes (Layout A bars + FLIP)
static/host.js                       ✏️  WS handler poll_host_update, renderPollResults, FLIP, fetchPollState
static/participant.html              ✏️  #activity-poll-section, state vars, WS handlers,
                                           _renderActivityPoll, castPollVote, _applyPollState,
                                           _resetActivityState extension,
                                           _ws.onopen re-fetch fix

tests/daemon/poll/test_poll_router.py       ✏️  extend with /vote tests + edge cases
tests/daemon/poll/test_poll_persistence.py  🆕  snapshot + restore round-trip
tests/docker/test_poll_live.py              🆕  hermetic E2E (steps 1–16 above)
tests/pages/host_page.py                    ✏️  poll helpers
tests/pages/participant_page.py             ✏️  poll helpers

docs/openapi.yaml                    ✏️  regenerate after router changes
API.md                               ✏️  regenerate via scripts/generate_apis_md.py
```
