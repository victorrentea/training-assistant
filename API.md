# API Reference (Generated from Contracts)

Generated from `docs/openapi.yaml`, `docs/participant-ws.yaml`, and `docs/host-ws.yaml`.

## Table of Contents
- [Session Management](#feature-session-management)
- [Identity](#feature-identity)
- [Slides](#feature-slides)
- [Activity Switching](#feature-activity-switching)
- [Poll](#feature-poll)
- [Word Cloud](#feature-word-cloud)
- [Q&A](#feature-qa)
- [Code Review](#feature-code-review)
- [Debate](#feature-debate)
- [Scores & Leaderboard](#feature-scores--leaderboard)
- [Emoji Reactions](#feature-emoji-reactions)
- [Quiz Generation](#feature-quiz-generation)
- [Paste & File Upload](#feature-paste--file-upload)
- [Notes & Summary](#feature-notes--summary)
- [Feedback](#feature-feedback)
- [Transcription](#feature-transcription)
- [Cross-cutting: Reload](#feature-cross-cutting-reload)

## Feature: Session Management

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Daemon Status<br>`GET /api/daemon-status` | - | `{code_timestamp: string \| null}` |
| Get Log Level<br>`GET /api/log-level` | - | `{level: 'info' \| 'debug'}` |
| Set Log Level<br>`POST /api/log-level` | `{level: 'info' \| 'debug'}` | - |
| Get Session Active, public endpoint: returns the active session_id or null.<br>`GET /api/session/active` | - | `{session_id: string \| null}` |
| Host starts a new session (creates folder, assigns session_id, clean slate).<br>`POST /api/session/create` | `name: string`<br>`type: 'workshop' \| 'conference'` | `session_name: string`<br>`session_id: string` |
| Host ends the current session. Railway closes WS connections on session end.<br>`POST /api/session/end` | - | - |
| Host ends the current session. Railway closes WS connections on session end.<br>`POST /api/session/end_talk` | - | - |
| List Session Folders<br>`GET /api/session/folders` | - | `{folders: list[string]}` |
| Host resumes an existing session folder. Uses session-state.json as persisted storage.<br>`POST /api/session/resume` | `{folder: string}` | `session_name: string`<br>`session_id: string` |
| Host starts a nested talk (conference mode).<br>`POST /api/session/start_talk` | - | - |
| Get Interval Lines Txt, return raw transcript lines for a time window; returns text/plain interval lines for session export/inspection.<br>`GET /api/{session_id}/session/interval-lines.txt` | - | `text/plain: string` |

## Feature: Identity

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Refresh Avatar Endpoint, re-roll avatar (conference mode only).<br>`POST /api/participant/avatar` | `{rejected?: list[string]}` | `ok?: bool`<br>`avatar: string` |
| Set Location, store participant city/timezone.<br>`POST /api/participant/location` | `{location: string}` | - |
| Rename Participant, returns 400 if not yet registered.<br>`PUT /api/participant/name` | `{name: string}` | - |
| Register Participant, idempotent for returning participants.<br>`POST /api/participant/register` | - | `name: string`<br>`avatar: string` |
| Get Participant State, return full personalised state for a participant — used on page load and WS reconnect; returns participant-personalized full state snapshot.<br>`GET /api/participant/state` | - | `type?: string`<br>`mode: string`<br>`my_score: int`<br>`my_name: string`<br>`my_avatar: string`<br>`current_activity: string`<br>`participant_count: int`<br>`host_connected: bool`<br>`daemon_connected: bool`<br>`wordcloud_words: dict[str, int]`<br>`wordcloud_word_order: list[string]`<br>`wordcloud_topic: string`<br>`qa_questions: list[QAQuestionRaw]`<br>`poll?: PollData \| null`<br>`poll_active: bool`<br>`vote_counts: dict[str, int]`<br>`poll_timer_seconds?: int \| null`<br>`poll_timer_started_at?: string \| null`<br>`poll_correct_ids?: list[string] \| null`<br>`my_vote?: string \| list[string] \| null`<br>`my_voted_ids?: list[string] \| null`<br>`codereview: CodeReviewParticipantState`<br>`debate_statement?: string \| null`<br>`debate_phase?: string \| null`<br>`debate_my_side?: string \| null`<br>`debate_my_is_champion: bool`<br>`debate_side_counts: dict[str, int]`<br>`debate_arguments: list[DebateArgumentParticipant]`<br>`debate_champions: dict[str, string]`<br>`debate_auto_assigned: list[string]`<br>`debate_first_side?: string \| null`<br>`debate_round_index?: int \| null`<br>`debate_round_timer_seconds?: int \| null`<br>`debate_round_timer_started_at?: string \| null`<br>`slides_current?: SlidesCurrentPayload \| null`<br>`session_main?: SessionMainPayload \| null`<br>`session_name?: string \| null`<br>`leaderboard_data?: LeaderboardData \| null`<br>`summary_count: int`<br>`notes_count: int`<br><br>`QAQuestionRaw {`<br>`  id: string`<br>`  text: string`<br>`  author_uuid: string`<br>`  upvoter_uuids: list[string]`<br>`  answered: bool`<br>`  timestamp: number`<br>`}`<br><br>`PollData {`<br>`  id: string`<br>`  question: string`<br>`  options: list[PollOption]`<br>`  multi: bool`<br>`  correct_count?: int \| null`<br>`  source?: string \| null`<br>`  page?: string \| null`<br>`}`<br><br>`CodeReviewParticipantState {`<br>`  snippet?: string \| null`<br>`  language?: string \| null`<br>`  phase?: string \| null`<br>`  confirmed_lines?: list[int]`<br>`  my_selections?: list[int]`<br>`  line_percentages?: dict[str, int] \| null`<br>`}`<br><br>`DebateArgumentParticipant {`<br>`  id: string`<br>`  author_uuid: string`<br>`  side: string`<br>`  text: string`<br>`  upvoters: list[string]`<br>`  ai_generated: bool`<br>`  merged_into?: string \| null`<br>`  is_own: bool`<br>`  has_upvoted: bool`<br>`}`<br><br>`SlidesCurrentPayload {`<br>`  slug?: string \| null`<br>`}`<br><br>`SessionMainPayload {`<br>`  mode?: string \| null`<br>`}`<br><br>`LeaderboardData {`<br>`  entries: list[LeaderboardEntry]`<br>`  total_participants: int`<br>`}`<br><br>`PollOption {`<br>`  id: string`<br>`  text: string`<br>`}`<br><br>`LeaderboardEntry {`<br>`  uuid: string`<br>`  name: string`<br>`  score: int`<br>`}` |

### Participant WS
| Message | Payload |
| --- | --- |
| `participant_count_updated` | `{count: int}` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Host State, return full state for host page load — replicates Railway build_for_host(); returns host-facing full state snapshot.<br>`GET /api/{session_id}/host/state` | - | `type?: string`<br>`mode: string`<br>`current_activity: string`<br>`participant_count: int`<br>`participants: list[HostParticipant]`<br>`daemon_connected: bool`<br>`overlay_connected: bool`<br>`wordcloud_words: dict[str, int]`<br>`wordcloud_word_order: list[string]`<br>`wordcloud_topic: string`<br>`qa_questions: list[HostQAQuestion]`<br>`poll?: PollData \| null`<br>`poll_active: bool`<br>`vote_counts: dict[str, int]`<br>`votes: dict[str, HostPollVote]`<br>`poll_timer_seconds?: int \| null`<br>`poll_timer_started_at?: string \| null`<br>`poll_correct_ids?: list[string] \| null`<br>`codereview: HostCodeReviewState`<br>`debate_statement?: string \| null`<br>`debate_phase?: string \| null`<br>`debate_side_counts: dict[str, int]`<br>`debate_sides: dict[str, string]`<br>`debate_arguments: list[DebateArgumentHost]`<br>`debate_champions: dict[str, string]`<br>`debate_auto_assigned: list[string]`<br>`debate_first_side?: string \| null`<br>`debate_round_index?: int \| null`<br>`debate_round_timer_seconds?: int \| null`<br>`debate_round_timer_started_at?: string \| null`<br>`slides_current?: SlidesCurrentPayload \| null`<br>`slides_log: list[SlidesLogEntry]`<br>`slides_log_deep_count: int`<br>`slides_log_topic?: string \| null`<br>`session_main?: SessionMainPayload \| null`<br>`session_name?: string \| null`<br>`session_id?: string \| null`<br>`join_base_url: string`<br>`daemon_session_folder?: string \| null`<br>`daemon_session_notes?: string \| null`<br>`leaderboard_data?: LeaderboardData \| null`<br>`summary_count: int`<br>`summary_updated_at?: string \| null`<br>`notes_count: int`<br>`token_usage: TokenUsage`<br>`transcript_line_count: int`<br>`transcript_total_lines: int`<br>`transcript_latest_ts?: string \| null`<br>`quiz_preview?: QuizPreviewPayload-Output \| null`<br><br>`HostParticipant {`<br>`  uuid: string`<br>`  name: string`<br>`  score: int`<br>`  location: string`<br>`  avatar: string`<br>`  paste_texts?: list[PasteEntry]`<br>`  received_files?: list[UploadedFileEntry]`<br>`}`<br><br>`HostQAQuestion {`<br>`  id: string`<br>`  text: string`<br>`  author: string`<br>`  author_uuid: string`<br>`  author_avatar: string`<br>`  upvote_count: int`<br>`  upvoters: list[string]`<br>`  answered: bool`<br>`  timestamp: number`<br>`}`<br><br>`PollData {`<br>`  id: string`<br>`  question: string`<br>`  options: list[PollOption]`<br>`  multi: bool`<br>`  correct_count?: int \| null`<br>`  source?: string \| null`<br>`  page?: string \| null`<br>`}`<br><br>`HostPollVote {`<br>`  option_ids: list[string]`<br>`  voted_at: string`<br>`}`<br><br>`HostCodeReviewState {`<br>`  snippet?: string \| null`<br>`  language?: string \| null`<br>`  phase?: string \| null`<br>`  confirmed_lines?: list[int]`<br>`  selections?: dict[str, list[int]]`<br>`  line_percentages?: dict[str, int] \| null`<br>`  line_counts?: dict[str, int] \| null`<br>`}`<br><br>`DebateArgumentHost {`<br>`  id: string`<br>`  author_uuid: string`<br>`  side: string`<br>`  text: string`<br>`  upvoters: list[string]`<br>`  ai_generated: bool`<br>`  merged_into?: string \| null`<br>`}`<br><br>`SlidesCurrentPayload {`<br>`  slug?: string \| null`<br>`}`<br><br>`SlidesLogEntry {`<br>`  file: string`<br>`  slide: int`<br>`  seconds_spent: number`<br>`  timestamp: string`<br>`}`<br><br>`SessionMainPayload {`<br>`  mode?: string \| null`<br>`}`<br><br>`LeaderboardData {`<br>`  entries: list[LeaderboardEntry]`<br>`  total_participants: int`<br>`}`<br><br>`TokenUsage {`<br>`  input_tokens: int`<br>`  output_tokens: int`<br>`  estimated_cost_usd: number`<br>`}`<br><br>`QuizPreviewPayload-Output {`<br>`  question?: string \| null`<br>`  options?: list[string] \| null`<br>`  multi?: bool \| null`<br>`  correct_indices?: list[int] \| null`<br>`}`<br><br>`PasteEntry {`<br>`  id: string`<br>`  text: string`<br>`}`<br><br>`UploadedFileEntry {`<br>`  id: string`<br>`  filename: string`<br>`  size: int`<br>`  disk_path: string`<br>`  seen_by_host: bool`<br>`}`<br><br>`PollOption {`<br>`  id: string`<br>`  text: string`<br>`}`<br><br>`LeaderboardEntry {`<br>`  uuid: string`<br>`  name: string`<br>`  score: int`<br>`}` |

### Host WS
| Message | Payload |
| --- | --- |
| Participant list changed (join/register/rename/location) — sent by daemon directly<br>`participant_list_updated` | `{participants: list[HostParticipant]}`<br><br>`HostParticipant {`<br>`  uuid: string`<br>`  name: string`<br>`  score: int`<br>`  location?: string \| null`<br>`  avatar: string`<br>`}` |

## Feature: Slides

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Slides Cache Status, primarily for diagnostics; UI cache invalidation is event-driven via slides_cache_status WS.<br>`GET /api/participant/slides-cache-status` | - | `{slides_cache_status?: dict[str, SlidesCacheStatusEntry]}`<br><br>`SlidesCacheStatusEntry {`<br>`  status: string`<br>`  size_bytes?: int \| null`<br>`  downloaded_at?: string \| null`<br>`  modified_at?: string \| null`<br>`  title?: string \| null`<br>`  name?: string \| null`<br>`  error?: string \| null`<br>`}` |

### Participant WS
| Message | Payload |
| --- | --- |
| Host navigated to a new slide<br>`slides_current` | `{slides_current?: SlidesCurrent  # null means no active slide}`<br><br>`SlidesCurrent {`<br>`  url?: string \| null`<br>`  slug?: string \| null`<br>`  presentation_name?: string \| null`<br>`  current_page?: int \| null`<br>`  updated_at?: string \| null`<br>`}` |
| Invalidation signal — participant must call GET /api/slides to refresh<br>Client must refetch slide list; payload intentionally carries no cache map.<br>`slides_cache_status` | - |

### Host WS
| Message | Payload |
| --- | --- |
| Invalidation signal — host must call GET /api/slides to refresh<br>Host should refetch slides list; payload intentionally carries no cache map.<br>`slides_cache_status` | - |

## Feature: Activity Switching

### Participant WS
| Message | Payload |
| --- | --- |
| `activity_updated` | `{current_activity: 'none' \| 'poll' \| 'wordcloud' \| 'qa' \| 'codereview' \| 'debate'}` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Host sets the current activity.<br>`POST /api/{session_id}/host/activity` | `{activity: string}` | `ok?: bool`<br>`current_activity: string` |
| Host sets the current activity.<br>`PUT /api/{session_id}/host/activity` | `{activity: string}` | `ok?: bool`<br>`current_activity: string` |

## Feature: Poll

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Participant casts a vote. Votes are final once submitted; re-vote is rejected.<br>`POST /api/participant/poll/vote` | `{option_ids: list[string]}` | - |

### Participant WS
| Message | Payload |
| --- | --- |
| Poll opened for voting<br>Participants can vote only while poll is open.<br>`poll_opened` | `{poll: Poll}`<br><br>`Poll {`<br>`  id: string`<br>`  question: string`<br>`  options: list[object]`<br>`  multi: bool`<br>`}` |
| Voting closed by host<br>`poll_closed` | `vote_counts: dict[str, int]  # option_id → vote count`<br>`total_votes: int` |
| Host revealed correct answers<br>`poll_correct_revealed` | `{correct_ids: list[string]}` |
| Poll removed by host<br>`poll_cleared` | - |
| Host started a countdown timer for the poll<br>`poll_timer_started` | `{seconds: int}` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Host deletes the current poll.<br>`DELETE /api/{session_id}/host/poll` | - | - |
| Host creates a new poll.<br>`POST /api/{session_id}/host/poll` | `question?: string`<br>`options?: list[PollOptionRequest]`<br>`multi?: bool`<br>`correct_count?: int \| null`<br><br>`PollOptionRequest {`<br>`  id: string`<br>`  text: string`<br>`}` | `ok?: bool`<br>`poll: PollResponse`<br><br>`PollResponse {`<br>`  id: string`<br>`  question: string`<br>`  options: list[PollOptionRequest]`<br>`  multi: bool`<br>`  correct_count?: int \| null`<br>`  source?: string \| null`<br>`  page?: string \| null`<br>`}`<br><br>`PollOptionRequest {`<br>`  id: string`<br>`  text: string`<br>`}` |
| Host closes the poll.<br>`POST /api/{session_id}/host/poll/close` | - | `ok?: bool`<br>`vote_counts: dict[str, int]`<br>`total_votes: int` |
| Host reveals correct answers and awards scores.<br>`PUT /api/{session_id}/host/poll/correct` | `{correct_ids?: list[string]}` | - |
| Host opens the poll for voting.<br>`POST /api/{session_id}/host/poll/open` | - | - |
| Set Poll Status, compatibility: {open: true} → open_poll, {open: false} → close_poll.<br>`PUT /api/{session_id}/host/poll/status` | `{open: bool}` | `OkResponse \| ClosePollResponse`<br><br>`OkResponse {`<br>`  ok?: bool`<br>`}`<br><br>`ClosePollResponse {`<br>`  ok?: bool`<br>`  vote_counts: dict[str, int]`<br>`  total_votes: int`<br>`}` |
| Host starts a countdown timer for the poll.<br>`POST /api/{session_id}/host/poll/timer` | `{seconds?: int}` | - |

### Host WS
| Message | Payload |
| --- | --- |
| Host-only notification when a new poll is created (before opening)<br>`poll_ai_generated` | `{poll: dict  # Poll data {id, question, options[], multi}}` |
| Real-time vote tally while poll is open<br>Host-only event; participants do not receive live vote tallies.<br>`vote_update` | `{votes: dict[str, int]  # option_id → vote count}` |

## Feature: Word Cloud

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Participant submits a word to the word cloud.<br>`POST /api/participant/wordcloud/word` | `{word: string}` | - |

### Participant WS
| Message | Payload |
| --- | --- |
| Word cloud state changed (new word or topic update)<br>`wordcloud_updated` | `words: dict[str, int]  # word → count`<br>`word_order: list[string]  # Newest-first insertion order`<br>`topic: string` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Host clears the word cloud.<br>`POST /api/{session_id}/host/wordcloud/clear` | - | - |
| Host sets the word cloud topic.<br>`POST /api/{session_id}/host/wordcloud/topic` | `{topic: string}` | - |
| Host submits a word — same as participant but no scoring.<br>`POST /api/{session_id}/host/wordcloud/word` | `{word: string}` | - |

### Host WS
| Message | Payload |
| --- | --- |
| Word cloud updated (same payload as participant)<br>`wordcloud_updated` | `words: dict[str, int]  # word → count`<br>`word_order: list[string]  # Words ordered newest first`<br>`topic: string` |

## Feature: Q&A

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Participant submits a Q&A question.<br>`POST /api/participant/qa/submit` | `{text: string}` | - |
| Participant upvotes a Q&A question.<br>`POST /api/participant/qa/upvote` | `{question_id: string}` | - |

### Participant WS
| Message | Payload |
| --- | --- |
| Q&A list changed (new question, upvote, edit, delete)<br>`qa_updated` | `{questions: list[QAQuestion]}`<br><br>`QAQuestion {`<br>`  id: string`<br>`  text: string`<br>`  author_uuid: string`<br>`  upvoter_uuids: list[string]  # Client computes is_own and has_upvoted locally from its own UUID`<br>`  answered: bool`<br>`  timestamp: number`<br>`}` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Host clears all Q&A questions.<br>`POST /api/{session_id}/host/qa/clear` | - | - |
| Host deletes a question.<br>`DELETE /api/{session_id}/host/qa/question/{question_id}` | - | - |
| Host toggles a question's answered flag.<br>`PUT /api/{session_id}/host/qa/question/{question_id}/answered` | `{answered?: bool}` | - |
| Host edits a question's text.<br>`PUT /api/{session_id}/host/qa/question/{question_id}/text` | `{text: string}` | - |
| Host submits a Q&A question — no scoring.<br>`POST /api/{session_id}/host/qa/submit` | `{text: string}` | - |

### Host WS
| Message | Payload |
| --- | --- |
| Q&A list changed (same structure as participant)<br>`qa_updated` | `{questions: list[QAQuestion]}`<br><br>`QAQuestion {`<br>`  id: string`<br>`  text: string`<br>`  author_uuid: string`<br>`  upvoter_uuids: list[string]`<br>`  answered: bool`<br>`  timestamp: number`<br>`}` |

## Feature: Code Review

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Update Selection, participant sets their selected lines (full replacement).<br>`PUT /api/participant/codereview/selection` | `{lines?: list[int]}` | - |

### Participant WS
| Message | Payload |
| --- | --- |
| Host opened a code snippet for review<br>`codereview_opened` | `snippet: string`<br>`language: string \| null` |
| Host closed the line selection phase<br>`codereview_selection_closed` | - |
| Host confirmed a line as problematic<br>`codereview_line_confirmed` | `{line: int}` |
| Code review removed by host<br>`codereview_cleared` | - |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Host clears the code review.<br>`DELETE /api/{session_id}/host/codereview` | - | - |
| Host creates a code review session.<br>`POST /api/{session_id}/host/codereview` | `snippet: string`<br>`language?: string \| null`<br>`smart_paste?: bool` | - |
| Host confirms a line as problematic and awards points.<br>`PUT /api/{session_id}/host/codereview/confirm-line` | `{line: int}` | `ok?: bool`<br>`confirmed_line: int` |
| Set Codereview Status, host closes the selection phase.<br>`PUT /api/{session_id}/host/codereview/status` | `{open?: bool}` | `ok?: bool`<br>`phase: string` |

### Host WS
| Message | Payload |
| --- | --- |
| Aggregated line selection counts (host-only)<br>`codereview_selections_updated` | `{line_counts: dict[str, int]  # line number → count of participants who selected it}` |

## Feature: Debate

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Participant submits a debate argument.<br>`POST /api/participant/debate/argument` | `{text: string}` | - |
| Participant picks a side (for/against).<br>`POST /api/participant/debate/pick-side` | `{side: string}` | - |
| Participant upvotes a debate argument.<br>`POST /api/participant/debate/upvote` | `{argument_id: string}` | - |
| Participant volunteers as champion for their side.<br>`POST /api/participant/debate/volunteer` | - | - |

### Participant WS
| Message | Payload |
| --- | --- |
| Full debate state snapshot<br>`debate_updated` | `statement?: string \| null`<br>`phase?: null \| 'side_selection' \| 'arguments' \| 'ai_cleanup' \| 'prep' \| 'live_debate' \| 'ended' \| null`<br>`sides?: dict[str, string]  # uuid → "for"\|"against"`<br>`arguments?: list[DebateArgument]`<br>`champions?: dict[str, string]  # "for"\|"against" → uuid`<br>`auto_assigned?: list[string]`<br>`first_side?: string \| null`<br>`round_index?: int \| null`<br>`round_timer_seconds?: int \| null`<br>`round_timer_started_at?: string \| null`<br><br>`DebateArgument {`<br>`  id: string`<br>`  author_uuid: string`<br>`  side: 'for' \| 'against'`<br>`  text: string`<br>`  upvoters: list[string]`<br>`  ai_generated: bool`<br>`  merged_into?: string \| null`<br>`}` |
| A timed debate round started<br>`debate_timer` | `round_index: int`<br>`seconds: int`<br>`started_at: string` |
| `debate_round_ended` | - |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Host launches a debate with a statement.<br>`POST /api/{session_id}/host/debate` | `{statement: string}` | - |
| Receive Ai Result, manual/skip AI result — host posts AI cleanup results directly.<br>`POST /api/{session_id}/host/debate/ai-result` | `merges?: list[DebateAiMerge]`<br>`cleaned?: list[DebateAiCleaned]`<br>`new_arguments?: list[DebateAiNewArgument]`<br><br>`DebateAiMerge {`<br>`  keep_id: string`<br>`  remove_ids?: list[string]`<br>`}`<br><br>`DebateAiCleaned {`<br>`  id: string`<br>`  text: string`<br>`}`<br><br>`DebateAiNewArgument {`<br>`  side: string`<br>`  text: string`<br>`}` | - |
| Host closes side selection; auto-assigns remaining participants.<br>`POST /api/{session_id}/host/debate/close-selection` | - | - |
| Host ends arguments phase; triggers AI cleanup in background.<br>`POST /api/{session_id}/host/debate/end-arguments` | - | - |
| Host ends the current round early.<br>`POST /api/{session_id}/host/debate/end-round` | - | - |
| Set First Side, host picks which side speaks first in live debate.<br>`POST /api/{session_id}/host/debate/first-side` | `{side: string}` | - |
| Force Assign, host force-assigns all unassigned participants.<br>`POST /api/{session_id}/host/debate/force-assign` | - | - |
| Host advances the debate to a specific phase.<br>`POST /api/{session_id}/host/debate/phase` | `{phase: string}` | `ok?: bool`<br>`phase: string` |
| Host resets all debate state.<br>`POST /api/{session_id}/host/debate/reset` | - | - |
| Host starts a timed round.<br>`POST /api/{session_id}/host/debate/round-timer` | `round_index: int`<br>`seconds: int` | - |

## Feature: Scores & Leaderboard

### Participant WS
| Message | Payload |
| --- | --- |
| One or more participants' scores changed<br>`scores_updated` | `{scores: dict[str, int]  # uuid → score (all participants)}` |
| Leaderboard overlay shown with top positions<br>`leaderboard_revealed` | `{positions: list[LeaderboardPosition]}`<br><br>`LeaderboardPosition {`<br>`  rank: int`<br>`  name: string`<br>`  score: int`<br>`  avatar: string`<br>`}` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Hide Leaderboard<br>`POST /api/{session_id}/host/leaderboard/hide` | - | - |
| Show Leaderboard<br>`POST /api/{session_id}/host/leaderboard/show` | - | - |
| Reset Scores<br>`DELETE /api/{session_id}/host/scores` | - | - |

### Host WS
| Message | Payload |
| --- | --- |
| Leaderboard revealed (same payload as participant)<br>`leaderboard_revealed` | `{positions: list[LeaderboardPosition]}`<br><br>`LeaderboardPosition {`<br>`  rank: int`<br>`  name: string`<br>`  score: int`<br>`  avatar: string`<br>`}` |

## Feature: Emoji Reactions

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Emoji Reaction, participant sends an emoji reaction.<br>`POST /api/participant/emoji/reaction` | `{emoji: string}` | - |

### Host WS
| Message | Payload |
| --- | --- |
| Participant sent an emoji reaction — floating animation on host screen<br>`emoji_reaction` | `{emoji: string}` |

## Feature: Quiz Generation

### Participant WS
| Message | Payload |
| --- | --- |
| Quiz generation progress update<br>`quiz_status` | `status: string  # "generating"\|"ready"\|"error"`<br>`message: string` |
| Quiz preview for host review before publishing (quiz=null to clear)<br>`quiz_preview` | `quiz?: any \| null  # Set to null to clear the preview`<br>`question?: string`<br>`options?: list[string]`<br>`multi?: bool`<br>`correct_indices?: list[int]` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Host clears the current quiz preview.<br>`DELETE /api/{session_id}/host/quiz-preview` | - | - |
| Host requests regeneration of a specific question or option.<br>`POST /api/{session_id}/host/quiz-refine` | `target: string`<br>`preview?: QuizPreviewPayload-Input \| null`<br><br>`QuizPreviewPayload-Input {`<br>`  quiz?: dict[str, any] \| null`<br>`  question?: string \| null`<br>`  options?: list[string] \| null`<br>`  multi?: bool \| null`<br>`  correct_indices?: list[int] \| null`<br>`}` | - |
| Host requests a quiz — stores request for the orchestrator loop to pick up.<br>`POST /api/{session_id}/host/quiz-request` | `minutes?: int \| null`<br>`topic?: string \| null` | - |
| Get Quiz Md, return the accumulated quiz markdown history.<br>`GET /api/{session_id}/quiz-md` | - | `{content: string}` |

### Host WS
| Message | Payload |
| --- | --- |
| Quiz generation progress update<br>`quiz_status` | `status: string  # "generating" \| "ready" \| "error"`<br>`message?: string` |
| Generated quiz ready for host review (quiz=null to clear)<br>`quiz_preview` | `quiz?: any \| null  # Set to null to clear the preview`<br>`question?: string`<br>`options?: list[object]`<br>`multi?: bool`<br>`correct_indices?: list[int]` |

## Feature: Paste & File Upload

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Participant pastes text to be seen by host.<br>`POST /api/participant/paste` | `{text: string}` | - |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Pastes, return all pending paste entries grouped by participant uuid.<br>`GET /api/{session_id}/host/pastes` | - | `{pastes?: dict[str, list[PasteEntry]]}`<br><br>`PasteEntry {`<br>`  id: string`<br>`  text: string`<br>`}` |
| Mark Uploaded File Seen<br>`POST /api/{session_id}/host/uploads/seen` | `uuid: string`<br>`file_id: string` | - |

### Host WS
| Message | Payload |
| --- | --- |
| Participant submitted a text paste<br>`paste_received` | `uuid: string  # Participant UUID who submitted the paste`<br>`id: string  # Paste ID`<br>`text: string` |
| Participant uploaded a file (daemon has downloaded it to session folder)<br>`file_uploaded` | `uuid: string  # Participant UUID who uploaded the file`<br>`id: string  # File ID`<br>`filename: string`<br>`size: int  # File size in bytes`<br>`disk_path: string  # Absolute path on the host's disk where the file was saved by the daemon` |

## Feature: Notes & Summary

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Notes<br>`GET /api/participant/notes` | - | `{notes_content?: string \| null}` |
| Get Summary<br>`GET /api/participant/summary` | - | `points?: list[SummaryPoint]`<br>`raw_markdown?: string \| null`<br>`updated_at?: string \| null`<br><br>`SummaryPoint {`<br>`  text: string`<br>`  source: string`<br>`}` |

### Participant WS
| Message | Payload |
| --- | --- |
| Notes file changed — non-empty line count updated<br>`notes_updated` | `{count: int  # Number of non-empty lines in the notes file}` |
| AI summary file changed — parsed point count updated<br>`summary_updated` | `{count: int  # Number of parsed bullet-point objects in ai-summary.md}` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Host Notes, return current session notes content.<br>`GET /api/{session_id}/host/notes` | - | `{notes_content?: string \| null}` |
| Get Host Summary, return summary points, raw markdown, and updated_at timestamp.<br>`GET /api/{session_id}/host/summary` | - | `points?: list[SummaryPoint]`<br>`raw_markdown?: string \| null`<br>`updated_at?: string \| null`<br><br>`SummaryPoint {`<br>`  text: string`<br>`  source: string`<br>`}` |

### Host WS
| Message | Payload |
| --- | --- |
| Notes file changed — non-empty line count updated<br>`notes_updated` | `{count: int  # Number of non-empty lines in the notes file}` |
| AI summary file changed — parsed point count updated<br>`summary_updated` | `{count: int  # Number of parsed bullet-point objects in ai-summary.md}` |

## Feature: Feedback

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Participant Feedback<br>`POST /api/participant/misc/feedback` | `text: string`<br>`participant_name?: string \| null` | - |

## Feature: Transcription

### Participant WS
| Message | Payload |
| --- | --- |
| Daemon detected a transcription language change<br>`transcription_language_pending` | `{language: string}` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Host sets the transcription language — stores pending request for daemon/macos-addons. Accepted values: ro, en, auto.<br>`POST /api/transcription-language` | `{language: string}` | - |
| Poll Transcription Language Request, daemon/macos-addons polls for a pending language change request (clears on read); consumes and clears the pending transcription language request.<br>`GET /api/transcription-language/request` | - | `{request?: string \| null}` |

## Feature: Cross-cutting: Reload

### Participant WS
| Message | Payload |
| --- | --- |
| Daemon synced static files — browser should reload<br>Client should trigger full page reload to pick up new static assets.<br>`reload` | - |

### Host WS
| Message | Payload |
| --- | --- |
| Daemon synced static files — browser should reload<br>Host client should trigger full page reload to pick up new static assets.<br>`reload` | - |
