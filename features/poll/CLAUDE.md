# Poll

## Purpose
Manages the full lifecycle of a live poll: create, open, close, mark correct answers, and award Kahoot-style speed-based points. Participants vote once and cannot change their vote.

## Endpoints
- `POST /api/poll` — create a new poll (2–8 options, optional multi-select)
- `PUT /api/poll/status` — open (`open: true`) or close (`open: false`) the active poll
- `PUT /api/poll/correct` — mark correct option IDs, compute and award speed-based scores
- `POST /api/poll/timer` — start a countdown timer (1–120s), broadcast to all clients
- `DELETE /api/poll` — clear poll and reset to NONE activity
- `GET /api/quiz-md` — return all closed polls as markdown (used by daemon for quiz generation)
- `GET /api/suggest-name` — suggest a unique display name for a new participant
- `GET /api/status` — public status endpoint (backend version, participant count, current poll)
- `POST /api/pending-deploy` — notify clients of a pending deploy (called by deploy watcher)

## WebSocket Messages
- `vote` → single-option vote (broadcast `vote_update` with live counts)
- `multi_vote` → multi-option vote (broadcast `vote_update`)
- `result` (server → participant) → sent after correct answers revealed; includes `correct_ids`, `voted_ids`, `score`
- `timer` (server → all) → broadcast when host starts countdown
- `deploy_pending` (server → all) → broadcast when a new deploy is detected

## State Fields
Fields in `AppState` owned by this feature:
- `poll: dict | None` — `{id, question, multi, correct_count, options[], source, page}`
- `poll_active: bool` — whether voting is currently open
- `votes: dict[str, str | list]` — uuid → voted option_id(s)
- `poll_opened_at: datetime | None` — timestamp when poll was opened (for speed scoring)
- `poll_correct_ids: list[str] | None` — correct option IDs after reveal
- `poll_timer_seconds: int | None` — timer duration
- `poll_timer_started_at: datetime | None` — timer start time
- `vote_times: dict[str, datetime]` — uuid → first vote timestamp
- `base_scores: dict[str, int]` — scores snapshot at poll open (for delta calculation)
- `quiz_md_content: str` — accumulated closed polls as markdown

## Design Decisions
- Votes are final: once cast, a vote cannot be changed.
- Speed bonus uses a linear decay from `_MAX_POINTS` (1000) to `_MIN_POINTS` (500) within `_SLOWEST_MULTIPLIER` (3x) the fastest voter's time.
- Multi-select scoring: proportional `(R - W) / C` ratio, floored at 0.
- `state.current_activity` is set to `POLL` on create, `NONE` on delete.
- Guard: cannot create poll if another activity is active (returns 409).
