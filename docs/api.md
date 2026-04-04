# Training Assistant — Full API Reference

Single-page reference for the entire API surface, organised by feature.

## Architecture

```
Participant Browser ── REST ──> Railway (proxy) ── WS proxy_request ──> Daemon localhost:8081
                    <── WS ────────────────────── broadcast fan-out ──<

Host Browser ── REST ────────────────────────────────────────────────> Daemon localhost:8081
             <── WS ─────────────────────────────────────────────────<
```

- **Participant REST**: proxied through Railway → daemon. Headers: `X-Participant-ID: <uuid>`.
- **Host REST**: called directly on `localhost:8081`. Auth: HTTP Basic.
- **Participant WS**: receive-only. Full state from `GET /api/participant/state` on connect. Incremental events via WS broadcast.
- **Host WS**: receive-only. Full state from `GET /api/{session_id}/host/state` on connect.
- **Session ID**: required in all host REST paths and WS paths as `{session_id}`.

---

## Feature: Identity / Participants

### Participant REST API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/participant/name` | Register or return existing identity |
| POST | `/api/participant/avatar` | Re-roll avatar (conference mode only) |
| POST | `/api/participant/location` | Store city or timezone string |
| GET  | `/api/participant/state`  | Full personalised state snapshot |

**POST /api/participant/name** body: `{name: string}`.
Response: `{ok, name, avatar, returning?, universe?}`.
If `returning=true`, the stored name/avatar is returned unchanged.
On conflict, a LOTR name fallback is assigned automatically.
Conference mode with empty name auto-assigns a character name.

**POST /api/participant/avatar** body: `{rejected: string[]}`.
Response: `{ok, avatar}`.

**POST /api/participant/location** body: `{location: string}`.
Response: `{ok}`.

**GET /api/participant/state** — returns full personalised state (see `state` WS event schema in participant-ws.yaml).

### Write-back events (emitted by daemon after identity requests)

These events are sent to Railway via the `X-Write-Back-Events` response header and fanned out to all participants:

- `participant_registered` — `{type, participant_id, name, avatar, universe, score, debate_side}`
- `participant_avatar_updated` — `{type, participant_id, avatar}`
- `participant_location` — `{type, participant_id, location}`

### Participant WS Events (receive-only)

No identity-specific incremental events; identity changes are reflected in the next `participant_count` broadcast.

### Host REST API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/{session_id}/host/state` | Full host state snapshot |

### Daemon State — `ParticipantState`

| Field | Type | Description |
|-------|------|-------------|
| `participant_names` | `dict[uuid, str]` | UUID → display name |
| `participant_avatars` | `dict[uuid, str]` | UUID → avatar filename or `"letter:XX:color"` |
| `participant_universes` | `dict[uuid, str]` | UUID → character universe (conference mode) |
| `scores` | `dict[uuid, int]` | UUID → total score |
| `locations` | `dict[uuid, str]` | UUID → city/timezone string |
| `mode` | `str` | `"workshop"` or `"conference"` |
| `current_activity` | `str` | `"none"|"poll"|"wordcloud"|"qa"|"codereview"|"debate"` |

---

## Feature: Poll

### Participant REST API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/participant/poll/vote` | Cast a vote |

**POST /api/participant/poll/vote**
- Single-select: `{option_id: string}`
- Multi-select: `{option_ids: string[]}`

Response: `{ok}` or `{error: "Vote rejected"}` (409).
Votes are final — re-voting on single-select is rejected.

### Host REST API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/{session_id}/poll` | Create a new poll |
| POST | `/api/{session_id}/poll/open` | Open poll for voting |
| POST | `/api/{session_id}/poll/close` | Close voting |
| PUT  | `/api/{session_id}/poll/correct` | Reveal correct answers and award scores |
| POST | `/api/{session_id}/poll/timer` | Start countdown timer |
| DELETE | `/api/{session_id}/poll` | Delete poll |
| GET  | `/api/{session_id}/quiz-md` | Get accumulated quiz markdown history |

**POST poll** body: `{question, options: [{id, text}], multi?, correct_count?, source?, page?}`

**PUT correct** body: `{correct_ids: string[]}`

**POST timer** body: `{seconds: int}` (default 30)

### Participant WS Events (receive-only)

| Event type | Trigger | Key fields |
|-----------|---------|-----------|
| `poll_opened` | Host opens poll | `poll: {id, question, options, multi, correct_count?, source?, page?}` |
| `poll_closed` | Host closes poll | `vote_counts: {option_id: count}`, `total_votes` |
| `poll_correct_revealed` | Host reveals answers | `correct_ids[]`, `scores: {uuid: pts}`, `votes: {uuid: selection}` |
| `poll_cleared` | Host deletes poll | — |
| `poll_timer_started` | Host starts timer | `seconds`, `started_at` (ISO datetime) |

### Host WS Events (receive-only)

| Event type | Trigger | Key fields |
|-----------|---------|-----------|
| `poll_created` | Host creates poll | `poll` object |
| `poll_opened` | Host opens poll | `poll` object |
| `poll_closed` | Host closes poll | `vote_counts`, `total_votes` |
| `poll_correct_revealed` | Correct revealed | `correct_ids[]`, `scores`, `votes` |
| `poll_cleared` | Poll deleted | — |
| `poll_timer_started` | Timer started | `seconds`, `started_at` |
| `scores_updated` | Score change | `scores: {uuid: pts}` |

### Daemon State — `PollState`

| Field | Type | Description |
|-------|------|-------------|
| `poll` | `dict\|None` | `{id, question, options, multi, correct_count?, source?, page?}` |
| `poll_active` | `bool` | True when voting is open |
| `votes` | `dict[uuid, str\|list]` | UUID → option_id (single) or list of option_ids (multi) |
| `vote_times` | `dict[uuid, datetime]` | Vote timestamp per UUID (for speed scoring) |
| `poll_opened_at` | `datetime\|None` | When poll was opened (UTC) |
| `poll_correct_ids` | `list[str]\|None` | Revealed correct option IDs |
| `poll_timer_seconds` | `int\|None` | Timer duration |
| `poll_timer_started_at` | `datetime\|None` | Timer start time (UTC) |
| `quiz_md_content` | `str` | Accumulated Q&A markdown history |

**Scoring**: 500–1000 pts for correct votes, speed-weighted. Multi-select: partial credit = ratio `(correct – wrong) / total_correct`.

---

## Feature: Word Cloud

### Participant REST API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/participant/wordcloud/word` | Submit a word (activity gate: `wordcloud`) |

**POST word** body: `{word: string}` (max 40 chars). Response: `{ok}`. Awards 200 points.

### Host REST API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/{session_id}/wordcloud/word` | Submit a word (no scoring) |
| POST | `/api/{session_id}/wordcloud/topic` | Set the topic prompt |
| POST | `/api/{session_id}/wordcloud/clear` | Clear all words and topic |

**POST topic** body: `{topic: string}`

### Participant WS Events (receive-only)

| Event type | Trigger | Key fields |
|-----------|---------|-----------|
| `wordcloud_updated` | Any word/topic/clear change | `words: {word: count}`, `word_order: string[]`, `topic: string` |

### Host WS Events (receive-only)

Same `wordcloud_updated` event (sent via broadcast fan-out from participant writes, and directly for host writes).

### Daemon State — `WordCloudState`

| Field | Type | Description |
|-------|------|-------------|
| `words` | `dict[str, int]` | word → count (lowercase) |
| `word_order` | `list[str]` | Words in newest-first insertion order |
| `topic` | `str` | Topic prompt shown above the cloud |

---

## Feature: Q&A

### Participant REST API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/participant/qa/submit` | Submit a question |
| POST | `/api/participant/qa/upvote` | Upvote a question |

**POST submit** body: `{text: string}` (max 280 chars). Awards 100 pts to submitter.

**POST upvote** body: `{question_id: string}`. Awards 50 pts to author, 25 pts to upvoter.
Cannot upvote own question or upvote twice.

### Host REST API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/{session_id}/qa/submit` | Host submits a question (no scoring) |
| PUT  | `/api/{session_id}/qa/question/{qid}/text` | Edit question text |
| DELETE | `/api/{session_id}/qa/question/{qid}` | Delete question |
| PUT  | `/api/{session_id}/qa/question/{qid}/answered` | Toggle answered flag |
| POST | `/api/{session_id}/qa/clear` | Clear all questions |

**PUT text** body: `{text: string}`
**PUT answered** body: `{answered: bool}`

### Participant WS Events (receive-only)

| Event type | Trigger | Key fields |
|-----------|---------|-----------|
| `qa_updated` | Any Q&A change | `questions: [{id, text, author, author_uuid, author_avatar, upvoters[], upvote_count, answered, timestamp}]` |
| `scores_updated` | Score awarded | `scores: {uuid: pts}` |

Note: `is_own` and `has_upvoted` are computed client-side from `author_uuid` and `upvoters[]`.

### Host WS Events (receive-only)

| Event type | Trigger | Key fields |
|-----------|---------|-----------|
| `qa_updated` | Any Q&A change | `questions` with full detail (no personalisation) |
| `scores_updated` | Score awarded | `scores` |

### Daemon State — `QAState`

| Field | Type | Description |
|-------|------|-------------|
| `questions` | `dict[qid, dict]` | `{id, text, author: uuid, upvoters: set[uuid], answered, timestamp}` |

Sorted for broadcast by `-upvote_count, timestamp` (most upvoted first, oldest first within tie).

---

## Feature: Code Review

### Participant REST API

| Method | Path | Description |
|--------|------|-------------|
| PUT | `/api/participant/codereview/selection` | Set selected lines (full replacement; activity gate: `codereview`, phase gate: `selecting`) |

**PUT selection** body: `{lines: int[]}` — zero-based line indices. Awards 200 pts per confirmed line that was selected.

### Host REST API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/{session_id}/codereview` | Create code review (smart-paste via Claude Haiku) |
| PUT  | `/api/{session_id}/codereview/status` | Close selection phase |
| PUT  | `/api/{session_id}/codereview/confirm-line` | Confirm a line as problematic |
| DELETE | `/api/{session_id}/codereview` | Clear code review |

**POST codereview** body: `{snippet, language?, smart_paste?}`. `smart_paste=true` (default) calls Claude Haiku to extract clean code and detect language. Max 50 lines.

**PUT status** body: `{open: false}` — transitions phase from `selecting` to `reviewing`.

**PUT confirm-line** body: `{line: int}` — zero-based. Awards 200 pts to all participants who selected that line.

### Participant WS Events (receive-only)

The following events are broadcast to participants but are NOT currently handled by participant.js — the participant page refreshes state via REST on reconnect only:

| Event type | Broadcast | Notes |
|-----------|---------|-------|
| `codereview_opened` | Yes | `{snippet, language}` — participant page refresh on next reconnect |
| `codereview_selection_closed` | Yes | Phase transition signal |
| `codereview_line_confirmed` | Yes | `{line: int}` |
| `codereview_cleared` | Yes | — |
| `codereview_selections_updated` | Yes | `{line_counts: {line: count}}` — host-oriented |
| `scores_updated` | Yes | `{scores}` — participant.js handles this |
| `activity_updated` | Yes | `{current_activity}` — participant.js does NOT handle this |

### Host WS Events (receive-only)

Same broadcast events flow through to host. Additionally, host state reflects code review via the full state object.

### Daemon State — `CodeReviewState`

| Field | Type | Description |
|-------|------|-------------|
| `snippet` | `str\|None` | Current code snippet |
| `language` | `str\|None` | Language identifier (`java`, `python`, etc.) |
| `phase` | `str` | `"idle"` / `"selecting"` / `"reviewing"` |
| `selections` | `dict[uuid, set[int]]` | UUID → set of selected line indices |
| `confirmed` | `set[int]` | Line indices confirmed by host |

---

## Feature: Debate

### Participant REST API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/participant/debate/pick-side` | Choose a side (activity gate: `debate`, phase gate: `side_selection`) |
| POST | `/api/participant/debate/argument` | Submit an argument (phase gate: `arguments`) |
| POST | `/api/participant/debate/upvote` | Upvote an argument |
| POST | `/api/participant/debate/volunteer` | Volunteer as champion (phase gate: `prep`) |

**POST pick-side** body: `{side: "for"|"against"}`. Auto-assignment triggers when ≥50% have picked.

**POST argument** body: `{text: string}` (max 280 chars). Awards 100 pts.

**POST upvote** body: `{argument_id: string}`. Awards 50 pts to author, 25 pts to upvoter. Cannot upvote own argument or upvote twice.

**POST volunteer** — No body. Awards 2500 pts.

### Host REST API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/{session_id}/debate` | Launch debate with a statement |
| POST | `/api/{session_id}/debate/reset` | Reset all debate state |
| POST | `/api/{session_id}/debate/close-selection` | Close side selection, auto-assign remaining |
| POST | `/api/{session_id}/debate/force-assign` | Force-assign ALL unassigned participants |
| POST | `/api/{session_id}/debate/phase` | Advance to a specific phase |
| POST | `/api/{session_id}/debate/first-side` | Set which side speaks first |
| POST | `/api/{session_id}/debate/round-timer` | Start a timed round |
| POST | `/api/{session_id}/debate/end-round` | End current round early |
| POST | `/api/{session_id}/debate/end-arguments` | End arguments phase (triggers AI cleanup) |
| POST | `/api/{session_id}/debate/ai-result` | Manually inject AI cleanup result |

**POST debate** body: `{statement: string}`

**POST phase** body: `{phase: "arguments"|"ai_cleanup"|"prep"|"live_debate"|"ended"}`

**POST first-side** body: `{side: "for"|"against"}`

**POST round-timer** body: `{round_index: int, seconds: int}`

**POST ai-result** body: `{merges: [{keep_id, remove_ids[]}], cleaned: [{id, text}], new_arguments: [{side, text}]}`

### Participant WS Events (receive-only)

| Event type | Trigger | Key fields |
|-----------|---------|-----------|
| `debate_updated` | Any debate state change | Full debate snapshot (see below) — broadcast to participants but NOT currently handled by participant.js |
| `debate_timer` | Round timer started | `round_index`, `seconds`, `started_at` |
| `debate_round_ended` | Round ended early | `round_index` |
| `scores_updated` | Score awarded | `scores: {uuid: pts}` |
| `activity_updated` | Debate launched/reset | `{current_activity}` — not handled by participant.js |

**debate_updated payload**: all fields from `DebateState.snapshot()` plus participant personalisation when applicable.

### Host WS Events (receive-only)

| Event type | Key fields |
|-----------|-----------|
| `debate_updated` | Full debate snapshot |
| `debate_timer` | `round_index`, `seconds`, `started_at` |
| `debate_round_ended` | `round_index` |
| `scores_updated` | `scores` |

### Daemon State — `DebateState`

| Field | Type | Description |
|-------|------|-------------|
| `statement` | `str\|None` | Debate statement |
| `phase` | `str\|None` | `side_selection` / `arguments` / `ai_cleanup` / `prep` / `live_debate` / `ended` |
| `sides` | `dict[uuid, str]` | UUID → `"for"` or `"against"` |
| `arguments` | `list[dict]` | `{id, author_uuid, side, text, upvoters: set, ai_generated, merged_into}` |
| `champions` | `dict[str, str]` | `"for"|"against"` → champion UUID |
| `auto_assigned` | `set[uuid]` | UUIDs auto-assigned to balance teams |
| `first_side` | `str\|None` | `"for"` or `"against"` — who speaks first |
| `round_index` | `int\|None` | Current round index (0–3) |
| `round_timer_seconds` | `int\|None` | Timer duration |
| `round_timer_started_at` | `datetime\|None` | Timer start (UTC) |

---

## Feature: Leaderboard

### Host REST API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/{session_id}/leaderboard/show` | Show top-5 leaderboard overlay |
| POST | `/api/{session_id}/leaderboard/hide` | Hide leaderboard overlay |
| DELETE | `/api/{session_id}/scores` | Reset all scores to zero |

### Participant WS Events (receive-only)

| Event type | Trigger | Key fields |
|-----------|---------|-----------|
| `leaderboard_revealed` | Host shows leaderboard | `entries: [{uuid, name, score}]` (top 5), `total_participants` |
| `leaderboard_hide` | Host hides leaderboard | — |
| `scores_updated` | Scores reset | `scores: {uuid: 0}` |

### Host WS Events (receive-only)

Same `leaderboard_revealed` and `leaderboard_hide` events.

### Daemon State — `LeaderboardState`

| Field | Type | Description |
|-------|------|-------------|
| `active` | `bool` | Whether the overlay is currently visible |
| `data` | `dict\|None` | Last-shown `{entries, total_participants}` (kept after hide for reconnecting participants) |

### Daemon State — `Scores`

| Field | Type | Description |
|-------|------|-------------|
| `scores` | `dict[uuid, int]` | Current total score per UUID |
| `base_scores` | `dict[uuid, int]` | Score snapshot taken when poll opens (for speed-scoring delta) |

---

## Feature: Activity

### Host REST API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/{session_id}/activity` | Switch current activity |

**POST activity** body: `{activity: "none"|"poll"|"wordcloud"|"qa"|"codereview"|"debate"}`

### Participant WS Events (receive-only)

| Event type | Trigger | Key fields |
|-----------|---------|-----------|
| `activity_updated` | Activity changed | `current_activity: string` — broadcast to participants but NOT currently handled by participant.js |

### Host WS Events (receive-only)

`activity_updated` — same payload (participant.js ignores; state is refreshed on reconnect).

---

## Feature: Emoji Reactions

### Participant REST API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/participant/emoji/reaction` | Send an emoji reaction |

**POST reaction** body: `{emoji: string}` (max 4 chars). No scoring.

### Host WS Events (receive-only)

| Event type | Trigger | Key fields |
|-----------|---------|-----------|
| `emoji_reaction` | Participant sends emoji | `emoji: string` |

Emoji events go directly to `send_to_host()` and to the desktop overlay (`localhost:56789/emoji`). They are NOT broadcast to other participants.

---

## Feature: Quiz (Daemon-driven)

### Host REST API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/{session_id}/quiz-request` | Request quiz generation |
| DELETE | `/api/{session_id}/quiz-preview` | Clear current quiz preview |
| POST | `/api/{session_id}/quiz-refine` | Regenerate a specific question or option |
| GET  | `/api/{session_id}/quiz-md` | Get accumulated quiz markdown history |

**POST quiz-request** body: `{minutes: int}` (transcript mode) OR `{topic: string}` (topic mode). Not both.

**POST quiz-refine** body: `{target: "question"|"opt0"|"opt1"|..., preview?: object}`

### Host WS Events (receive-only)

| Event type | Trigger | Key fields |
|-----------|---------|-----------|
| `quiz_status` | Daemon status update | `status: "requested"|"generating"|"error"`, `message: string` |
| `quiz_preview` | Daemon generated preview | `quiz: {question, options[], multi, correct_indices[], source?, page?}` or `null` |

---

## Feature: Slides (Navigation + Drive Sync)

### Host REST API

Slides host endpoints are proxied through from Railway (host JS calls via the Railway URL). See `host-api.yaml` for the full specification.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/slides` | Get current slides manifest |
| POST | `/api/slides/current` | Set current slide (daemon auto-detects from activity file) |
| DELETE | `/api/slides/current` | Clear current slide |
| GET | `/api/slides/file/{slug}` | Get PDF file |
| POST | `/api/slides/upload/{slug}` | Upload a PDF slide deck |
| POST | `/api/slides/drive-sync` | Trigger Google Drive sync for a deck |
| GET | `/api/slides/cache-status` | Get slide cache status |

### Participant WS Events (receive-only)

| Event type | Trigger | Key fields |
|-----------|---------|-----------|
| `slides_current` | Host advances slide | `slides_current: {url, slug, presentation_name, current_page, updated_at}` or `null` |
| `slides_updated` | A PDF was updated | `slug`, `updated_at` |
| `slides_catalog_changed` | Daemon (dis)connected or new deck | — |
| `slides_cache_status` | Cache status changed | `slides_cache_status: {slug: {…}}` |

### Host WS Events (receive-only)

Same events plus `slides_cache_status`.

### Daemon-to-Railway WS messages (internal)

These are sent by the daemon to Railway over the daemon WS connection (not to participants directly):

| Message type | Direction | Key fields |
|-------------|-----------|-----------|
| `slides_current` | daemon → Railway | `url, slug, source_file, presentation_name, current_page` |
| `slides_clear` | daemon → Railway | — |
| `slides_catalog` | daemon → Railway | `entries: [{name, slug, url, …}]` |
| `slide_invalidated` | daemon → Railway | `slug` |

---

## Feature: Session Management

### Host REST API

Session endpoints are called via Railway or daemon depending on the operation.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/{session_id}/host/state` | Full host state |
| POST | `/api/session/request` | Create/start/stop/rename a session (triggers daemon via WS) |
| GET | `/api/session/folders` | List available session folders |
| POST | `/api/session/sync` | Daemon pushes session state to Railway |

### Daemon-to-Railway WS messages (internal)

| Message type | Direction | Description |
|-------------|-----------|-------------|
| `session_folders` | daemon → Railway | Push list of available session folders from local disk |
| `session_sync` | daemon → Railway | Sync session state (main info + snapshot) |
| `global_state_saved` | daemon → Railway | Ack a `global_state_saved` request |

### Railway-to-Daemon WS messages (internal)

| Message type | Direction | Description |
|-------------|-----------|-------------|
| `session_request` | Railway → daemon | `{action: "create"|"start"|"stop"|"rename", name, session_id?, …}` |
| `state_snapshot_result` | Railway → daemon | Full state snapshot every ~7s for backup |
| `session_snapshot_result` | Railway → daemon | Session-specific snapshot |
| `daemon_state_push` | Railway → daemon | Push current participant/feature state on WS connect |
| `scores_reset` | Railway → daemon | Host reset scores |
| `summary_force` | Railway → daemon | Force summary regeneration |
| `summary_full_reset` | Railway → daemon | Full reset + regeneration |
| `sync_files` | Railway → daemon | Send static file hashes for diff-upload |

---

## Feature: Misc (Paste, Feedback, Notes, Summary)

### Participant REST API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/participant/misc/paste` | Send text to host (max 10 per participant, max 100 KB each) |
| POST | `/api/participant/misc/feedback` | Submit anonymous feedback (max 2000 chars) |
| GET  | `/api/participant/misc/notes` | Get session notes content |
| GET  | `/api/participant/misc/summary` | Get summary points and raw markdown |
| GET  | `/api/participant/misc/slides-cache-status` | Get slides cache status |

### Host REST API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/{session_id}/misc/paste-dismiss` | Dismiss a participant paste entry |
| GET  | `/api/{session_id}/misc/feedback` | Get and clear pending feedback items |

**POST paste-dismiss** body: `{uuid: string, paste_id: int}`

### Global REST API (no session_id)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/transcription-language` | Set transcription language (queued for macos-addons) |
| GET  | `/api/transcription-language/request` | Poll pending language request (clears on read) |

**POST transcription-language** body: `{language: "ro"|"en"|"auto"}`

### Participant WS Events (receive-only)

| Event type | Trigger | Key fields |
|-----------|---------|-----------|
| `paste_received` | Participant pastes text | `uuid`, `id: int`, `text: string` — broadcast to all (participants see others' pastes too) |
| `paste_dismissed` | Host dismisses paste | `uuid`, `paste_id: int` |
| `transcription_language_pending` | Language change queued | `language: string` |

### Host WS Events (receive-only)

| Event type | Trigger | Key fields |
|-----------|---------|-----------|
| `notes` | Notes file changed on disk | `notes_content: string\|null` |
| `summary` | AI summary updated | `points[]`, `updated_at`, `raw_markdown` |
| `transcription_language` | Language change confirmed | `language: string` |
| `transcription_language_pending` | Language change queued | `language: string` |

### Daemon State — `MiscState`

| Field | Type | Description |
|-------|------|-------------|
| `paste_texts` | `dict[uuid, list[{id, text}]]` | Pending paste entries per participant |
| `paste_next_id` | `int` | Auto-incrementing paste ID |
| `feedback_pending` | `list[str]` | Feedback awaiting email notification |
| `notes_content` | `str\|None` | Current session notes content |
| `summary_points` | `list[{text, source, time}]` | AI-generated summary bullet points |
| `summary_raw_markdown` | `str\|None` | Full markdown summary |
| `summary_updated_at` | `str\|None` | ISO timestamp of last update |
| `slides_cache_status` | `dict[slug, dict]` | PDF cache status per slide deck |
| `slides_current` | `dict\|None` | Current slide info (synced from Railway) |
| `session_main` | `dict\|None` | Main session info (synced from Railway) |
| `session_name` | `str\|None` | Session display name (synced from Railway) |

---

## Feature: Mode

### Host REST API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/mode` | Switch workshop/conference mode |

**POST mode** body: `{mode: "workshop"|"conference"}`

---

## Daemon-to-Railway Orchestrator Messages

These messages are sent by the daemon's main loop to Railway over the daemon WS connection.

| Message type | Frequency | Description |
|-------------|-----------|-------------|
| `broadcast` | On state change | `{type: "broadcast", event: {type: "...", ...}}` — fan-out to all participant WSs |
| `slides_current` | On slide change | Current slide pointer from `activity-slides-YYYY-MM-DD.md` |
| `slides_clear` | On slide clear | No active slide |
| `transcript_status` | Every 10s | `{line_count, total_lines, latest_ts}` |
| `token_usage` | Every 10s | `{input_tokens, output_tokens, estimated_cost_usd}` |
| `notes_content` | On file change | `{content: string}` |
| `activity_log` | On git file change | `{git_repos: [{url, branch, files[]}]}` |
| `session_folders` | On connect | List of session folders from local disk |
| `quiz_status` | On quiz progress | `{status, message}` |
| `quiz_preview` | On generation complete | `{quiz: {...}}` |
| `reload` | After static file sync | Signal browsers to reload |
| `state_restore` | When Railway lost state | Full state backup payload |

---

## WebSocket Connection Lifecycle

### Participant

1. JS opens WS: `WS wss://interact.victorrentea.ro/{session_id}/{uuid}`
2. On `onopen`: call `POST /api/participant/name`, then `GET /api/participant/state`
3. State response injected as `{type: "state"}` into `handleMessage()`
4. All subsequent WS messages are incremental broadcasts
5. On disconnect: 3-second retry

### Host

1. JS opens WS: `WS ws://localhost:8081/{session_id}/__host__`
2. On `onopen`: call `GET /api/{session_id}/host/state`
3. State response injected as `{type: "state"}` into `handleWSMessage()`
4. All subsequent WS messages are incremental events from daemon
5. On disconnect: 3-second retry
6. Multiple host tabs: old tab receives `{type: "kicked"}` and closes

### Daemon (internal)

1. Daemon connects to `WS wss://interact.victorrentea.ro/ws/daemon` with Basic Auth
2. On connect: Railway sends `sync_files` and `daemon_state_push`
3. Daemon sends `session_folders`, then re-syncs active session state
4. Daemon loop: drains received messages every ~100ms, sends broadcasts and status updates
5. On disconnect: 3-second retry

---

## Error Responses

All REST endpoints return `{error: string}` with appropriate HTTP status codes:

| Code | Meaning |
|------|---------|
| 400 | Bad request (missing/invalid body fields) |
| 409 | Conflict (already voted, cannot upvote own question, etc.) |
| 404 | Not found (unknown question_id, etc.) |
| 401/403 | Auth required (host endpoints) |

---

## Cross-Reference

| Document | Purpose |
|---------|---------|
| `docs/participant-api.yaml` | OpenAPI 3.0 spec for all participant REST endpoints |
| `docs/host-api.yaml` | OpenAPI 3.0 spec for all host REST endpoints |
| `docs/participant-ws.yaml` | AsyncAPI 2.6 spec for participant WS events |
| `docs/host-ws.yaml` | AsyncAPI 2.6 spec for host WS events |
| `docs/messaging-registry.md` | State builder / broadcast registry architecture |
| `docs/daemon-persisted-state.md` | What daemon persists to disk |
| `ARCHITECTURE.md` | C4 diagrams and system interaction sequence diagrams |
