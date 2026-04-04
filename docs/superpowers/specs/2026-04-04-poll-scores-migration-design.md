# Phase 4c: Poll + Scores + Leaderboard Migration — Design Spec

## Goal

Migrate poll (voting, scoring, timer, correct reveal), scores (global authority), and leaderboard to the daemon. Daemon becomes the single score authority; Railway keeps a **read-only score mirror** (updated by daemon broadcasts) so unmigrated features (codereview state builder, session snapshot, core state builder) continue working. Refactor quiz integration to call poll state directly. Clean up Q&A/wordcloud `score_award` and `wordcloud_state_sync` write-backs.

## Architecture

```
Participant Browser          Railway (BE)                    Daemon (Mac)
┌──────────────┐        ┌──────────────────┐          ┌──────────────────┐
│ POST /vote   │──REST──│ proxy_bridge     │──WS────> │ poll/router.py   │
│              │        │ (dumb pipe)      │          │ poll/state.py    │
│              │<──WS───│ broadcast fan-out│<──WS──── │ scores.py        │
│              │        │                  │          │ quiz/poll_api.py │
└──────────────┘        └──────────────────┘          └──────────────────┘

Host Browser ──── REST ──────────────────────────────> Daemon localhost:8081
```

Daemon owns all poll state, all scoring, and leaderboard. Railway keeps a read-only score mirror (updated by daemon broadcasts) for unmigrated features that still read `state.scores`.

## Design Decisions

### No backward compatibility

Each migration phase produces the final architecture. No dead code, no state sync write-backs. Old WS handlers and Railway endpoints are deleted, not kept. This applies retroactively — `wordcloud_state_sync` write-back from Phase 4a is also removed.

### Daemon owns scores globally

Scores move from Railway `AppState` to daemon as the single authority. A new `daemon/scores.py` module holds the global `scores: dict[str, int]` and `base_scores: dict[str, int]`. All features that award points (poll, Q&A, wordcloud) use this module. The `score_award` WS message type is removed.

**Read-only score mirror on Railway:** Many unmigrated Railway features still read `state.scores`: core state builder (participant `my_score`, host participant list), core messaging (`historical_participant_ids`), codereview state builder, session restore, snapshot. Rather than modifying all of them, Railway keeps `state.scores` as a **read-only mirror** updated by a new `_handle_scores_updated` broadcast handler. Railway never writes to `state.scores` — only the daemon does (via broadcast events). The mirror is removed when the remaining features are migrated.

**Codereview scoring:** Codereview confirm-line (`features/codereview/router.py`) currently writes `state.scores[pid] += 200`. It now sends a `codereview_score_award` WS message to daemon instead. Daemon applies the scores and broadcasts `scores_updated`, which updates Railway's mirror.

**Leaderboard:** Migrated to daemon in this phase (3 small endpoints). `broadcast_leaderboard()` in `core/messaging.py` is removed. Leaderboard broadcast becomes unpersonalized.

### Daemon is the clock for vote timing

Vote timestamps are recorded when daemon processes the vote. The extra ~50ms WS hop is identical for all participants, so fairness is preserved.

### No live vote counts during voting

`vote_update` broadcast is removed. Participants see results only after the host closes the poll. This prevents the bandwagon effect and matches the redesign spec.

### Unpersonalized broadcasts everywhere

`poll_correct_revealed` sends `{correct_ids, scores, votes}` — each client picks its own data by UUID. `leaderboard_revealed` sends `{entries, total_participants}` — each client computes own rank by UUID. No per-participant messages. Follows the "ZERO personalization on BE" principle.

### Quiz calls poll state directly

`daemon/quiz/poll_api.py` stops sending `poll_create`/`poll_open` WS messages. Instead calls `poll_state.create_poll()` and `poll_state.open_poll()` directly, then triggers broadcasts via `_ws_client`.

### Votes are final (single-select)

For single-select polls, once a participant votes, the vote is locked — `cast_vote()` rejects if `pid` is already in `self.votes`. For multi-select, toggling is allowed (the participant can update their selection set until the poll closes). This matches the existing client behavior and the "Votes are final" design decision.

### Poll state is daemon-only (no Railway restore)

Poll state is not included in `daemon_state_push` from Railway. The daemon owns poll state; it persists across daemon WS reconnects because the daemon process stays alive. If the daemon process restarts, poll state is lost (acceptable for live events). `vote_times`, `poll_opened_at`, and timer state are transient and never persisted.

### Thread safety on scoring

`Scores.add_score()` acquires the lock because proxy requests run in a `ThreadPoolExecutor` — concurrent Q&A submissions and wordcloud entries can race.

## New Files

### `daemon/scores.py` — Global score authority

```python
import threading

class Scores:
    def __init__(self):
        self._lock = threading.Lock()
        self.scores: dict[str, int] = {}      # uuid → total score
        self.base_scores: dict[str, int] = {}  # uuid → score at poll open

    def add_score(self, pid: str, points: int):
        with self._lock:
            self.scores[pid] = self.scores.get(pid, 0) + points

    def snapshot_base(self):
        """Capture current scores as base (called when poll opens)."""
        with self._lock:
            self.base_scores = dict(self.scores)

    def reset(self):
        with self._lock:
            self.scores.clear()
            self.base_scores.clear()

    def sync_from_restore(self, data: dict):
        with self._lock:
            if "scores" in data:
                self.scores.clear()
                self.scores.update(data["scores"])
            if "base_scores" in data:
                self.base_scores.clear()
                self.base_scores.update(data.get("base_scores", {}))

    def snapshot(self) -> dict:
        return dict(self.scores)

scores = Scores()
```

### `daemon/poll/state.py` — Poll state singleton

```python
import threading
from datetime import datetime, timezone

_MAX_POINTS = 1000
_MIN_POINTS = 500
_SLOWEST_MULTIPLIER = 3

class PollState:
    def __init__(self):
        self._lock = threading.Lock()
        self.poll: dict | None = None
        self.poll_active: bool = False
        self.votes: dict[str, str | list] = {}        # uuid → option_id or [option_ids]
        self.vote_times: dict[str, datetime] = {}      # uuid → first vote timestamp
        self.poll_opened_at: datetime | None = None
        self.poll_correct_ids: list[str] | None = None
        self.poll_timer_seconds: int | None = None
        self.poll_timer_started_at: datetime | None = None
        self._vote_counts_dirty: bool = True
        self._vote_counts_cache: dict | None = None
        self.quiz_md_content: str = ""                 # accumulated closed polls as markdown

    def create_poll(self, question: str, options: list[dict], multi: bool = False,
                    correct_count: int | None = None, source: str | None = None,
                    page: str | None = None) -> dict:
        """Create a new poll. Returns the poll object."""
        import uuid as _uuid
        self.poll = {
            "id": _uuid.uuid4().hex[:8],
            "question": question,
            "options": options,
            "multi": multi,
        }
        if correct_count is not None:
            self.poll["correct_count"] = correct_count
        if source:
            self.poll["source"] = source
        if page:
            self.poll["page"] = page
        self.poll_active = False
        self.votes.clear()
        self.vote_times.clear()
        self.poll_correct_ids = None
        self.poll_timer_seconds = None
        self.poll_timer_started_at = None
        self._vote_counts_dirty = True
        return dict(self.poll)

    def open_poll(self, scores_snapshot_fn) -> None:
        """Open voting. scores_snapshot_fn captures current scores as base."""
        self.poll_active = True
        self.poll_opened_at = datetime.now(timezone.utc)
        self.votes.clear()
        self.vote_times.clear()
        self._vote_counts_dirty = True
        scores_snapshot_fn()

    def close_poll(self) -> dict:
        """Close voting. Returns {vote_counts, total_votes}."""
        self.poll_active = False
        counts = self.vote_counts()
        total = len(self.votes)
        return {"vote_counts": counts, "total_votes": total}

    def cast_vote(self, pid: str, option_id: str = None, option_ids: list[str] = None) -> bool:
        """Record a vote. Returns True if accepted, False if rejected.
        Single-select: votes are final (reject if already voted).
        Multi-select: toggling allowed (overwrite selection set)."""
        if not self.poll or not self.poll_active:
            return False

        valid_ids = [o["id"] for o in self.poll["options"]]
        is_multi = self.poll.get("multi", False)

        if is_multi:
            if option_ids is None:
                return False
            correct_count = self.poll.get("correct_count")
            max_allowed = correct_count if correct_count else len(valid_ids)
            if (not isinstance(option_ids, list)
                or len(option_ids) > max_allowed
                or len(set(option_ids)) != len(option_ids)
                or not all(oid in valid_ids for oid in option_ids)):
                return False
            self.votes[pid] = option_ids
        else:
            # Single-select: votes are final
            if pid in self.votes:
                return False
            if option_id is None or option_id not in valid_ids:
                return False
            self.votes[pid] = option_id

        # Record first vote time only
        if pid not in self.vote_times:
            self.vote_times[pid] = datetime.now(timezone.utc)

        self._vote_counts_dirty = True
        return True

    def reveal_correct(self, correct_ids: list[str], scores_obj) -> dict:
        """Compute speed-based scores, apply them, return broadcast payload.
        Returns {correct_ids, scores, votes}. Safe to call with no votes."""
        correct_set = set(correct_ids)
        now = datetime.now(timezone.utc)
        opened_at = self.poll_opened_at or now
        all_option_ids = {opt["id"] for opt in self.poll.get("options", [])}
        wrong_set = all_option_ids - correct_set
        multi = self.poll.get("multi", False)

        # Find correct voters for min-time calculation
        correct_voters = set()
        for pid, selection in self.votes.items():
            voted = set(selection) if isinstance(selection, list) else {selection}
            if multi and correct_set:
                R = len(voted & correct_set)
                W = len(voted & wrong_set)
                if max(0.0, (R - W) / len(correct_set)) > 0:
                    correct_voters.add(pid)
            else:
                if voted & correct_set:
                    correct_voters.add(pid)

        elapsed_times = [
            max(0.0, (self.vote_times.get(p, now) - opened_at).total_seconds())
            for p in correct_voters
        ]
        min_time = min(elapsed_times) if elapsed_times else 0.0

        # Score each voter
        for pid, selection in self.votes.items():
            voted = set(selection) if isinstance(selection, list) else {selection}
            if multi and correct_set:
                R = len(voted & correct_set)
                W = len(voted & wrong_set)
                C = len(correct_set)
                ratio = max(0.0, (R - W) / C)
                if ratio == 0:
                    continue
            else:
                if not (voted & correct_set):
                    continue
                ratio = 1.0

            elapsed = max(0.0, (self.vote_times.get(pid, now) - opened_at).total_seconds())
            speed_window = min_time * (_SLOWEST_MULTIPLIER - 1)
            if speed_window > 0:
                decay = min(1.0, (elapsed - min_time) / speed_window)
            else:
                decay = 0.0
            speed_pts = round(_MAX_POINTS - (_MAX_POINTS - _MIN_POINTS) * decay)
            pts = round(speed_pts * ratio)
            if pts > 0:
                scores_obj.add_score(pid, pts)

        self.poll_correct_ids = list(correct_set)
        self._append_to_quiz_md(correct_set)

        return {
            "correct_ids": list(correct_set),
            "scores": scores_obj.snapshot(),
            "votes": dict(self.votes),
        }

    def start_timer(self, seconds: int) -> dict:
        """Start countdown timer. Returns {seconds, started_at}."""
        self.poll_timer_seconds = seconds
        self.poll_timer_started_at = datetime.now(timezone.utc)
        return {
            "seconds": seconds,
            "started_at": self.poll_timer_started_at.isoformat(),
        }

    def clear(self) -> None:
        """Remove poll and reset all poll state."""
        self.poll = None
        self.poll_active = False
        self.votes.clear()
        self.vote_times.clear()
        self.poll_opened_at = None
        self.poll_correct_ids = None
        self.poll_timer_seconds = None
        self.poll_timer_started_at = None
        self._vote_counts_dirty = True

    def vote_counts(self) -> dict:
        """Compute option_id → count. Cached until _vote_counts_dirty is set."""
        if not self._vote_counts_dirty and self._vote_counts_cache is not None:
            return self._vote_counts_cache
        counts: dict[str, int] = {}
        for selection in self.votes.values():
            ids = selection if isinstance(selection, list) else [selection]
            for oid in ids:
                counts[oid] = counts.get(oid, 0) + 1
        self._vote_counts_cache = counts
        self._vote_counts_dirty = False
        return counts

    def _append_to_quiz_md(self, correct_set: set[str]):
        """Append closed poll to quiz markdown for quiz history."""
        if not self.poll:
            return
        lines = [f"### {self.poll['question']}\n"]
        for opt in self.poll["options"]:
            marker = "✓" if opt["id"] in correct_set else "✗"
            lines.append(f"- [{marker}] {opt['text']}")
        lines.append("")
        self.quiz_md_content += "\n".join(lines) + "\n"

poll_state = PollState()
```

**Note:** `PollState` has no `sync_from_restore()`. Poll state lives only on daemon — it is not pushed from Railway. If the daemon process restarts, poll state is lost (acceptable for live events). `quiz_md_content` is also transient — it accumulates during a session and resets on daemon restart.

### `daemon/poll/router.py` — Participant + host endpoints

**Participant router** (`/api/participant/poll/*`):

| Endpoint | Method | Body | Behavior |
|----------|--------|------|----------|
| `/vote` | POST | `{option_id}` or `{option_ids}` | Validate, record vote. No broadcast (no live counts). Return `{ok: true}` or 409 if already voted (single-select) |

No write-back events on vote — daemon owns poll state, no broadcast during open voting.

**Host router** (`/api/{session_id}/poll/*`):

| Endpoint | Method | Body | Behavior |
|----------|--------|------|----------|
| `/` | POST | `{question, options, multi?, correct_count?}` | Create poll. Broadcast `poll_opened` if auto-open, else just store |
| `/open` | POST | `{}` | Open voting, snapshot base scores. Broadcast `poll_opened` |
| `/close` | POST | `{}` | Close voting. Broadcast `poll_closed` with vote counts |
| `/correct` | PUT | `{correct_ids}` | Compute scores. Broadcast `poll_correct_revealed` + `scores_updated` |
| `/timer` | POST | `{seconds}` | Start countdown. Broadcast `poll_timer_started` |
| `/` | DELETE | — | Clear poll. Broadcast `poll_cleared` |

Host endpoints: `_ws_client.send()` for Railway broadcast + `send_to_host()` for host browser.

**Quiz history endpoint** (public, on host server):

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/{session_id}/quiz-md` | GET | Return accumulated closed polls as markdown |

### Codereview scoring (interim)

Codereview state (snippet, selections, phase) stays on Railway — migrated in a later phase. Only the scoring part changes: Railway's confirm-line endpoint sends a `codereview_score_award` WS message to daemon with the list of participant IDs to award. Daemon applies scores and broadcasts `scores_updated` (which also updates Railway's read-only mirror).

New daemon WS message handler:

| Message type | Payload | Action |
|---|---|---|
| `codereview_score_award` | `{participant_ids: [...], points: 200}` | `scores.add_score()` for each pid, broadcast `scores_updated` + `send_to_host()` |

### `daemon/leaderboard/router.py` — Leaderboard on daemon

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/{session_id}/leaderboard/show` | POST | Compute top-5 from `scores`, broadcast `leaderboard_revealed` (unpersonalized) + `send_to_host()` |
| `/api/{session_id}/leaderboard/hide` | POST | Broadcast `leaderboard_hide` |
| `/api/{session_id}/scores` | DELETE | `scores.reset()`, broadcast `scores_updated` |

`leaderboard_revealed` payload: `{entries: [{name, score, uuid}], total_participants}`. Client computes `your_rank` from `entries` + own UUID.

## Broadcast Events

| Event type | Trigger | Payload |
|------------|---------|---------|
| `poll_opened` | Host opens voting | `{poll}` — poll object with question, options, multi |
| `poll_closed` | Host closes voting | `{vote_counts, total_votes}` |
| `poll_correct_revealed` | Host reveals answers | `{correct_ids, scores, votes}` |
| `poll_cleared` | Host deletes poll | `{}` |
| `poll_timer_started` | Host starts countdown | `{seconds, started_at}` |
| `scores_updated` | Any score change | `{scores}` — full scores map |
| `leaderboard_revealed` | Host triggers reveal | `{entries, total_participants}` |
| `leaderboard_hide` | Host hides leaderboard | `{}` |

All events broadcast to participants via `_ws_client.send({"type": "broadcast", "event": ...})` and to host browser via `send_to_host(...)`.

## Removed from Railway

### Files deleted
- `features/poll/router.py`, `features/poll/state_builder.py`, `features/poll/__init__.py`
- `features/leaderboard/router.py`, `features/leaderboard/state_builder.py`, `features/leaderboard/__init__.py`
- `features/scores/router.py`, `features/scores/__init__.py` (orphan module, not mounted but references `state.scores`)

### Code removed
- `features/ws/router.py`: WS handlers for `vote`, `multi_vote`; `_record_vote_and_broadcast()` helper; `_handle_poll_create`, `_handle_poll_open` handlers + `MSG_POLL_CREATE`, `MSG_POLL_OPEN` from handler map
- `features/ws/router.py`: `_handle_score_award` handler + `MSG_SCORE_AWARD` from handler map; `_handle_wordcloud_state_sync` handler + `MSG_WORDCLOUD_STATE_SYNC` from handler map
- `features/ws/router.py`: score write in `_handle_state_restore` (`state.scores = restore_data["scores"]`) — daemon handles score persistence
- `core/state.py`: poll fields (`poll`, `poll_active`, `votes`, `vote_times`, `poll_opened_at`, `poll_timer_*`, `poll_correct_ids`, `_vote_counts_cache`, `quiz_md_content`); `add_score()` method; leaderboard field (`leaderboard_active`)
- `core/messaging.py`: `broadcast_leaderboard()` function and its lazy import of `_build_leaderboard_data`
- `main.py`: poll router mount, leaderboard router mount removed
- `daemon_state_push` in `features/ws/router.py`: remove poll fields; **keep scores** (daemon syncs from them on reconnect)

### What STAYS on Railway (read-only score mirror)
- `core/state.py`: `scores: dict[str, int]` and `base_scores: dict[str, int]` remain but are **never written by Railway code**. Updated only by the new `_handle_scores_updated` handler.
- `core/state_builder.py`: score reads (`state.scores.get(pid, 0)` for `my_score`, host participant list) stay unchanged — they read from the mirror.
- `core/messaging.py`: `historical_participant_ids()` reads `state.scores.keys()` — stays, reads from mirror.
- `features/codereview/state_builder.py`: reads `state.scores` — stays, reads from mirror.
- `features/session/router.py`: `state.scores.clear()` in session reset — **changed** to send `scores_reset` event to daemon instead. Score restore from snapshot removed (daemon owns persistence).
- `features/snapshot/router.py`: score serialization in snapshot — stays (reads mirror for backup), score restore removed (daemon restores its own scores).

### WS message types removed
- `MSG_POLL_CREATE`, `MSG_POLL_OPEN` (replaced by direct state calls)
- `MSG_SCORE_AWARD` (replaced by daemon `scores_updated` broadcast)
- `MSG_WORDCLOUD_STATE_SYNC` (no longer needed)

### New Railway handler
- `_handle_scores_updated(data)`: extracts `scores` from broadcast event payload, updates `state.scores` mirror. Registered in `_DAEMON_MSG_HANDLERS` to process `scores_updated` events alongside the generic `_handle_broadcast` fan-out. This keeps the mirror in sync for all unmigrated features that read scores.

## Modified Files

### `daemon/qa/router.py`
- Remove `score_award` write-back events from both `submit_question` and `upvote_question`
- Import `daemon.scores.scores` and call `scores.add_score()` directly
- Add `scores_updated` broadcast to write-back events for both submit and upvote paths:
  ```python
  {"type": "broadcast", "event": {"type": "scores_updated", "scores": scores.snapshot()}}
  ```
- Also `send_to_host({"type": "scores_updated", "scores": scores.snapshot()})` for host browser

### `daemon/wordcloud/router.py`
- Remove `score_award` write-back events
- Remove `wordcloud_state_sync` write-back events
- Import `daemon.scores.scores` and call `scores.add_score()` directly
- Add `scores_updated` broadcast to write-back events
- Also `send_to_host()` for host browser scores update

### `daemon/quiz/poll_api.py`
- `post_poll()`: call `poll_state.create_poll()` directly, then broadcast `poll_opened` via `_ws_client`
- `open_poll()`: call `poll_state.open_poll()` directly, then broadcast via `_ws_client`
- `fetch_quiz_history()`: read `poll_state.quiz_md_content` directly instead of HTTP fetch
- Remove WS message sends for `poll_create`/`poll_open`

### `daemon/__main__.py`
- Import `scores` from `daemon.scores`
- Import `poll_state` from `daemon.poll.state` (for quiz integration, not for state push)
- Add to `_handle_daemon_state_push`: `scores.sync_from_restore(data)` (scores are pushed from Railway on reconnect)
- Wire `set_ws_client` for poll router and leaderboard router
- Register `codereview_score_award` handler

### `daemon/host_server.py`
- Mount poll participant + host routers
- Mount leaderboard host router
- Mount quiz-md endpoint

### `features/codereview/router.py` (Railway — interim change)
- `confirm_line`: replace `state.scores[pid] = state.scores.get(pid, 0) + _CONFIRM_LINE_POINTS` with sending `codereview_score_award` to daemon:
  ```python
  awarded_pids = [pid for pid, lines in state.codereview_selections.items() if body.line in lines]
  if awarded_pids and state.daemon_ws:
      await state.daemon_ws.send_json({
          "type": "codereview_score_award",
          "participant_ids": awarded_pids,
          "points": _CONFIRM_LINE_POINTS,
      })
  ```
- Remove the `await broadcast_state()` after scoring — daemon's `scores_updated` broadcast handles this now

### `features/session/router.py` (Railway — interim change)
- Session reset: replace `state.scores.clear(); state.base_scores.clear()` with sending a `scores_reset` event to daemon via `state.daemon_ws`
- Score restore from snapshot: remove (daemon handles its own score persistence)

### `features/ws/router.py` (Railway)
- Remove `_handle_score_award`, `_handle_wordcloud_state_sync`, `_handle_poll_create`, `_handle_poll_open` handlers and their entries from `_DAEMON_MSG_HANDLERS`
- Remove poll fields from `daemon_state_push` payload; keep `scores` and `base_scores` (daemon syncs from them on reconnect)
- Add `_handle_scores_updated` handler: updates `state.scores` mirror from broadcast payload
- Add `codereview_score_award` handler: forwards to daemon (no Railway processing)
- Keep `_handle_broadcast` (generic fan-out)

### `static/participant.js`
- `castVote()`: switch from `sendWS('vote', ...)` / `sendWS('multi_vote', ...)` to `participantApi('poll/vote', {option_id})` or `participantApi('poll/vote', {option_ids})`
- Add WS message handlers:
  - `poll_opened`: show poll, reset vote state
  - `poll_closed`: show results (vote_counts, total_votes)
  - `poll_correct_revealed`: extract own vote from `msg.votes[myUUID]`, own score from `msg.scores[myUUID]`, show correct/incorrect
  - `poll_cleared`: hide poll
  - `poll_timer_started`: start countdown
  - `scores_updated`: update `myScore` from `msg.scores[myUUID]`
  - `leaderboard_revealed`: compute own rank from `msg.entries` using own UUID
  - `leaderboard_hide`: hide leaderboard overlay
- Remove handling of old `vote_update` messages (live counts during voting)
- Remove handling of per-participant `result` message
- Remove old `leaderboard` message handler (replaced by `leaderboard_revealed`)

### `static/host.js`
- Poll CRUD calls: change from Railway URLs to `daemonApi()` (localhost:8081)
- Leaderboard calls: change from Railway URLs to `daemonApi()`
- Score reset: change from Railway URL to `daemonApi()`
- Add handlers for poll and leaderboard broadcast events pushed via host WS
- Handle `scores_updated` for score display

## Known Limitations

- **Timer not restored on reconnect**: If daemon WS drops briefly while a countdown timer is active, participants won't see the restored timer. Daemon reconnects are rare and brief; timers are typically 10-30 seconds.
- **Poll state lost on daemon restart**: Poll state (current poll, votes, timer) is in-memory only. If the daemon process restarts mid-poll, the poll is lost. Acceptable for live events where the host can recreate.
- **`quiz_md_content` lost on daemon restart**: Accumulated quiz history resets. The quiz generator can function without history (it just might regenerate similar questions).

## Testing

- Unit tests for `PollState` scoring logic (speed-based, multi-select proportional, votes-are-final enforcement)
- Unit tests for `Scores` module (add with thread safety, reset, snapshot, sync_from_restore)
- Integration test: participant vote via REST proxy round-trip
- Integration test: host create → open → vote → close → reveal flow
- Integration test: quiz generates poll via direct state call
- Integration test: codereview confirm-line awards points via daemon
- Integration test: leaderboard show/hide/reset
- Verify Q&A/wordcloud still award points correctly after score_award removal
