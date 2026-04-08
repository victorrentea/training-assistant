# API Reference (Generated from Contracts)

Generated from `docs/openapi.yaml`, `docs/participant-ws.yaml`, and `docs/host-ws.yaml`.

## Table of Contents
- [Session Management](#feature-session-management)
- [Slides](#feature-slides)
- [Activity Switching](#feature-activity-switching)
- [Identity](#feature-identity)
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
| Get Session Active<br>Public endpoint: returns the active session_id or null.<br>`GET /api/session/active` | - | `any` |
| End Session<br>Host ends the current session. Railway closes WS connections on session end.<br>`POST /api/session/end` | - | `any` |
| End Talk<br>Host ends the nested talk.<br>`POST /api/session/end_talk` | - | `any` |
| List Session Folders<br>List available session folders.<br>`GET /api/session/folders` | - | `any` |
| Resume Session<br>Host resumes an existing session folder. Uses session-state.json as persisted storage.<br>`POST /api/session/resume` | `{folder: string}` | `any` |
| Start Session<br>Host starts a new session (creates folder, assigns session_id, clean slate).<br>`POST /api/session/start` | `name: string`<br>`type?: string` | `any` |
| Start Talk<br>Host starts a nested talk (conference mode).<br>`POST /api/session/start_talk` | - | `any` |
| Set Mode<br>Host switches session mode (workshop/conference).<br>`POST /api/{session_id}/host/mode` | `{mode: string}` | `any` |
| Get Interval Lines Txt<br>Return raw transcript lines for a time window.<br>Returns text/plain interval lines for session export/inspection.<br>`GET /api/{session_id}/session/interval-lines.txt` | - | `text/plain: string` |

## Feature: Slides

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Slides Cache Status<br>Get slides cache status.<br>Primarily for diagnostics; UI cache invalidation is event-driven via slides_cache_status WS.<br>`GET /api/participant/slides-cache-status` | - | `any` |

### Participant WS
| Message | Payload |
| --- | --- |
| `slides_current`<br>Note: Host navigated to a new slide | `{slides_current?: SlidesCurrent  # null means no active slide}` |
| `slides_cache_status`<br>Note: Invalidation signal — participant must call GET /api/slides to refresh<br>Note: Client must refetch slide list; payload intentionally carries no cache map. | - |

### Host WS
| Message | Payload |
| --- | --- |
| `slides_cache_status`<br>Note: Invalidation signal — host must call GET /api/slides to refresh<br>Note: Host should refetch slides list; payload intentionally carries no cache map. | - |

## Feature: Activity Switching

### Participant WS
| Message | Payload |
| --- | --- |
| `activity_updated`<br>Note: Current activity type changed by host | `{current_activity: 'none' \| 'poll' \| 'wordcloud' \| 'qa' \| 'codereview' \| 'debate'}` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Set Activity<br>Host switches the current activity.<br>`POST /api/{session_id}/host/activity` | `{activity: string}` | `any` |
| Set Activity<br>Host switches the current activity.<br>`PUT /api/{session_id}/host/activity` | `{activity: string}` | `any` |

## Feature: Identity

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Refresh Avatar Endpoint<br>Re-roll avatar (conference mode only).<br>`POST /api/participant/avatar` | `{rejected?: list[string]}` | `ok?: bool`<br>`avatar: string` |
| Set Location<br>Store participant city/timezone.<br>`POST /api/participant/location` | `{location: string}` | `{ok?: bool}` |
| Rename Participant<br>Rename a registered participant. Returns 400 if not yet registered.<br>`PUT /api/participant/name` | `{name: string}` | - |
| Register Participant<br>Register participant — assign name+avatar. Idempotent for returning participants.<br>`POST /api/participant/register` | - | `name: string`<br>`avatar: string` |
| Get Participant State<br>Return full personalised state for a participant — used on page load and WS reconnect.<br>Returns participant-personalized full state snapshot.<br>`GET /api/participant/state` | - | `any` |

### Participant WS
| Message | Payload |
| --- | --- |
| `participant_count_updated`<br>Note: Participant count changed | `{count: int}` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Host State<br>Return full state for host page load — replicates Railway build_for_host().<br>Returns host-facing full state snapshot.<br>`GET /api/{session_id}/host/state` | - | `any` |

### Host WS
| Message | Payload |
| --- | --- |
| `participant_list_updated`<br>Note: Participant list changed (join/register/rename/location) — sent by daemon directly | `{participants: list[HostParticipant]}` |

## Feature: Poll

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Cast Vote<br>Participant casts a vote.<br>Votes are final once submitted; re-vote is rejected.<br>`POST /api/participant/poll/vote` | `{option_ids: list[string]}` | `any` |

### Participant WS
| Message | Payload |
| --- | --- |
| `poll_opened`<br>Note: Poll opened for voting<br>Note: Participants can vote only while poll is open. | `{poll: Poll}` |
| `poll_closed`<br>Note: Voting closed by host | `vote_counts: dict[str, int]  # option_id → vote count`<br>`total_votes: int` |
| `poll_correct_revealed`<br>Note: Host revealed correct answers | `{correct_ids: list[string]}` |
| `poll_cleared`<br>Note: Poll removed by host | - |
| `poll_timer_started`<br>Note: Host started a countdown timer for the poll | `{seconds: int}` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Delete Poll<br>Host deletes the current poll.<br>`DELETE /api/{session_id}/host/poll` | - | `any` |
| Create Poll<br>Host creates a new poll.<br>`POST /api/{session_id}/host/poll` | `question?: string`<br>`options?: list[dict[str, any]]`<br>`multi?: bool`<br>`correct_count?: int \| null` | `any` |
| Close Poll<br>Host closes the poll.<br>`POST /api/{session_id}/host/poll/close` | - | `any` |
| Reveal Correct<br>Host reveals correct answers and awards scores.<br>`PUT /api/{session_id}/host/poll/correct` | `{correct_ids?: list[string]}` | `any` |
| Open Poll<br>Host opens the poll for voting.<br>`POST /api/{session_id}/host/poll/open` | - | `any` |
| Set Poll Status<br>Compatibility: {open: true} → open_poll, {open: false} → close_poll.<br>`PUT /api/{session_id}/host/poll/status` | `{open: bool}` | `any` |
| Start Timer<br>Host starts a countdown timer for the poll.<br>`POST /api/{session_id}/host/poll/timer` | `{seconds?: int}` | `any` |

### Host WS
| Message | Payload |
| --- | --- |
| `poll_ai_generated`<br>Note: Host-only notification when a new poll is created (before opening) | `{poll: dict  # Poll data {id, question, options[], multi}}` |
| `vote_update`<br>Note: Real-time vote tally while poll is open<br>Note: Host-only event; participants do not receive live vote tallies. | `{votes: dict[str, int]  # option_id → vote count}` |

## Feature: Word Cloud

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Submit Word<br>Participant submits a word to the word cloud.<br>`POST /api/participant/wordcloud/word` | `{word: string}` | `any` |

### Participant WS
| Message | Payload |
| --- | --- |
| `wordcloud_updated`<br>Note: Word cloud state changed (new word or topic update) | `words: dict[str, int]  # word → count`<br>`word_order: list[string]  # Newest-first insertion order`<br>`topic: string` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Clear Wordcloud<br>Host clears the word cloud.<br>`POST /api/{session_id}/host/wordcloud/clear` | - | `any` |
| Set Topic<br>Host sets the word cloud topic.<br>`POST /api/{session_id}/host/wordcloud/topic` | `{topic: string}` | `any` |
| Host Submit Word<br>Host submits a word — same as participant but no scoring.<br>`POST /api/{session_id}/host/wordcloud/word` | `{word: string}` | `any` |

### Host WS
| Message | Payload |
| --- | --- |
| `wordcloud_updated`<br>Note: Word cloud updated (same payload as participant) | `words: dict[str, int]  # word → count`<br>`word_order: list[string]  # Words ordered newest first`<br>`topic: string` |

## Feature: Q&A

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Submit Question<br>Participant submits a Q&A question.<br>`POST /api/participant/qa/submit` | `{text: string}` | `any` |
| Upvote Question<br>Participant upvotes a Q&A question.<br>`POST /api/participant/qa/upvote` | `{question_id: string}` | `any` |

### Participant WS
| Message | Payload |
| --- | --- |
| `qa_updated`<br>Note: Q&A list changed (new question, upvote, edit, delete) | `{questions: list[QAQuestion]}` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Clear Qa<br>Host clears all Q&A questions.<br>`POST /api/{session_id}/host/qa/clear` | - | `any` |
| Delete Question<br>Host deletes a question.<br>`DELETE /api/{session_id}/host/qa/question/{question_id}` | - | `any` |
| Toggle Answered<br>Host toggles a question's answered flag.<br>`PUT /api/{session_id}/host/qa/question/{question_id}/answered` | `{answered?: bool}` | `any` |
| Edit Question Text<br>Host edits a question's text.<br>`PUT /api/{session_id}/host/qa/question/{question_id}/text` | `{text: string}` | `any` |
| Host Submit Question<br>Host submits a Q&A question — no scoring.<br>`POST /api/{session_id}/host/qa/submit` | `{text: string}` | `any` |

### Host WS
| Message | Payload |
| --- | --- |
| `qa_updated`<br>Note: Q&A list changed (same structure as participant) | `{questions: list[QAQuestion]}` |

## Feature: Code Review

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Update Selection<br>Participant sets their selected lines (full replacement).<br>`PUT /api/participant/codereview/selection` | `{lines?: list[int]}` | `any` |

### Participant WS
| Message | Payload |
| --- | --- |
| `codereview_opened`<br>Note: Host opened a code snippet for review | `snippet: string`<br>`language: string \| null` |
| `codereview_selection_closed`<br>Note: Host closed the line selection phase | - |
| `codereview_line_confirmed`<br>Note: Host confirmed a line as problematic | `{line: int}` |
| `codereview_cleared`<br>Note: Code review removed by host | - |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Clear Codereview<br>Host clears the code review.<br>`DELETE /api/{session_id}/host/codereview` | - | `any` |
| Create Codereview<br>Host creates a code review session.<br>`POST /api/{session_id}/host/codereview` | `snippet: string`<br>`language?: string \| null`<br>`smart_paste?: bool` | `any` |
| Confirm Line<br>Host confirms a line as problematic and awards points.<br>`PUT /api/{session_id}/host/codereview/confirm-line` | `{line: int}` | `any` |
| Set Codereview Status<br>Host closes the selection phase.<br>`PUT /api/{session_id}/host/codereview/status` | `{open?: bool}` | `any` |

### Host WS
| Message | Payload |
| --- | --- |
| `codereview_selections_updated`<br>Note: Aggregated line selection counts (host-only) | `{line_counts: dict[str, int]  # line number → count of participants who selected it}` |

## Feature: Debate

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Submit Argument<br>Participant submits a debate argument.<br>`POST /api/participant/debate/argument` | `{text: string}` | `any` |
| Pick Side<br>Participant picks a side (for/against).<br>`POST /api/participant/debate/pick-side` | `{side: string}` | `any` |
| Upvote Argument<br>Participant upvotes a debate argument.<br>`POST /api/participant/debate/upvote` | `{argument_id: string}` | `any` |
| Volunteer Champion<br>Participant volunteers as champion for their side.<br>`POST /api/participant/debate/volunteer` | - | `any` |

### Participant WS
| Message | Payload |
| --- | --- |
| `debate_updated`<br>Note: Full debate state snapshot | `statement?: string \| null`<br>`phase?: null \| 'side_selection' \| 'arguments' \| 'ai_cleanup' \| 'prep' \| 'live_debate' \| 'ended' \| null`<br>`sides?: dict[str, string]  # uuid → "for"\|"against"`<br>`arguments?: list[DebateArgument]`<br>`champions?: dict[str, string]  # "for"\|"against" → uuid`<br>`auto_assigned?: list[string]`<br>`first_side?: string \| null`<br>`round_index?: int \| null`<br>`round_timer_seconds?: int \| null`<br>`round_timer_started_at?: string \| null` |
| `debate_timer`<br>Note: A timed debate round started | `round_index: int`<br>`seconds: int`<br>`started_at: string` |
| `debate_round_ended`<br>Note: Current debate round ended | - |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Launch Debate<br>Host launches a debate with a statement.<br>`POST /api/{session_id}/host/debate` | `{statement: string}` | `any` |
| Receive Ai Result<br>Manual/skip AI result — host posts AI cleanup results directly.<br>`POST /api/{session_id}/host/debate/ai-result` | `merges?: list[any]`<br>`cleaned?: list[any]`<br>`new_arguments?: list[any]` | `any` |
| Close Selection<br>Host closes side selection; auto-assigns remaining participants.<br>`POST /api/{session_id}/host/debate/close-selection` | - | `any` |
| End Arguments<br>Host ends arguments phase; triggers AI cleanup in background.<br>`POST /api/{session_id}/host/debate/end-arguments` | - | `any` |
| End Round<br>Host ends the current round early.<br>`POST /api/{session_id}/host/debate/end-round` | - | `any` |
| Set First Side<br>Host picks which side speaks first in live debate.<br>`POST /api/{session_id}/host/debate/first-side` | `{side: string}` | `any` |
| Force Assign<br>Host force-assigns all unassigned participants.<br>`POST /api/{session_id}/host/debate/force-assign` | - | `any` |
| Advance Phase<br>Host advances the debate to a specific phase.<br>`POST /api/{session_id}/host/debate/phase` | `{phase: string}` | `any` |
| Reset Debate<br>Host resets all debate state.<br>`POST /api/{session_id}/host/debate/reset` | - | `any` |
| Start Round Timer<br>Host starts a timed round.<br>`POST /api/{session_id}/host/debate/round-timer` | `round_index: int`<br>`seconds: int` | `any` |

## Feature: Scores & Leaderboard

### Participant WS
| Message | Payload |
| --- | --- |
| `scores_updated`<br>Note: One or more participants' scores changed | `{scores: dict[str, int]  # uuid → score (all participants)}` |
| `leaderboard_revealed`<br>Note: Leaderboard overlay shown with top positions | `{positions: list[LeaderboardPosition]}` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Hide Leaderboard<br>`POST /api/{session_id}/host/leaderboard/hide` | - | `any` |
| Show Leaderboard<br>`POST /api/{session_id}/host/leaderboard/show` | - | `any` |
| Reset Scores<br>`DELETE /api/{session_id}/host/scores` | - | `any` |

### Host WS
| Message | Payload |
| --- | --- |
| `leaderboard_revealed`<br>Note: Leaderboard revealed (same payload as participant) | `{positions: list[LeaderboardPosition]}` |

## Feature: Emoji Reactions

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Emoji Reaction<br>Participant sends an emoji reaction.<br>`POST /api/participant/emoji/reaction` | `{emoji: string}` | `any` |

### Host WS
| Message | Payload |
| --- | --- |
| `emoji_reaction`<br>Note: Participant sent an emoji reaction — floating animation on host screen | `{emoji: string}` |

## Feature: Quiz Generation

### Participant WS
| Message | Payload |
| --- | --- |
| `quiz_status`<br>Note: Quiz generation progress update | `status: string  # "generating"\|"ready"\|"error"`<br>`message: string` |
| `quiz_preview`<br>Note: Quiz preview for host review before publishing (quiz=null to clear) | `quiz?: any \| null  # Set to null to clear the preview`<br>`question?: string`<br>`options?: list[string]`<br>`multi?: bool`<br>`correct_indices?: list[int]` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Clear Quiz Preview<br>Host clears the current quiz preview.<br>`DELETE /api/{session_id}/host/quiz-preview` | - | `any` |
| Request Quiz Refine<br>Host requests regeneration of a specific question or option.<br>`POST /api/{session_id}/host/quiz-refine` | `target: string`<br>`preview?: any \| null` | `any` |
| Request Quiz<br>Host requests a quiz — stores request for the orchestrator loop to pick up.<br>`POST /api/{session_id}/host/quiz-request` | `minutes?: int \| null`<br>`topic?: string \| null` | `any` |
| Get Quiz Md<br>Return the accumulated quiz markdown history.<br>`GET /api/{session_id}/quiz-md` | - | `any` |

### Host WS
| Message | Payload |
| --- | --- |
| `quiz_status`<br>Note: Quiz generation progress update | `status: string  # "generating" \| "ready" \| "error"`<br>`message?: string` |
| `quiz_preview`<br>Note: Generated quiz ready for host review (quiz=null to clear) | `quiz?: any \| null  # Set to null to clear the preview`<br>`question?: string`<br>`options?: list[object]`<br>`multi?: bool`<br>`correct_indices?: list[int]` |

## Feature: Paste & File Upload

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Paste Text<br>Participant pastes text to be seen by host.<br>`POST /api/participant/paste` | `{text: string}` | `any` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Pastes<br>Return all pending paste entries grouped by participant uuid.<br>`GET /api/{session_id}/host/pastes` | - | `any` |
| Mark Uploaded File Seen<br>Mark an uploaded-file indicator as seen by host in daemon session state.<br>`POST /api/{session_id}/host/uploads/seen` | `uuid: string`<br>`file_id: string` | `any` |

### Host WS
| Message | Payload |
| --- | --- |
| `paste_received`<br>Note: Participant submitted a text paste | `uuid: string  # Participant UUID who submitted the paste`<br>`id: string  # Paste ID`<br>`text: string` |
| `file_uploaded`<br>Note: Participant uploaded a file (daemon has downloaded it to session folder) | `uuid: string  # Participant UUID who uploaded the file`<br>`id: string  # File ID`<br>`filename: string`<br>`size: int  # File size in bytes`<br>`disk_path: string  # Absolute path on the host's disk where the file was saved by the daemon` |

## Feature: Notes & Summary

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Notes<br>Get session notes content.<br>`GET /api/participant/notes` | - | `any` |
| Get Summary<br>Get summary points and raw markdown.<br>`GET /api/participant/summary` | - | `any` |

### Participant WS
| Message | Payload |
| --- | --- |
| `notes_updated`<br>Note: Notes file changed — non-empty line count updated | `{count: int  # Number of non-empty lines in the notes file}` |
| `summary_updated`<br>Note: AI summary file changed — parsed point count updated | `{count: int  # Number of parsed bullet-point objects in ai-summary.md}` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Host Notes<br>Return current session notes content.<br>`GET /api/{session_id}/host/notes` | - | `any` |
| Get Host Summary<br>Return summary points, raw markdown, and updated_at timestamp.<br>`GET /api/{session_id}/host/summary` | - | `any` |

### Host WS
| Message | Payload |
| --- | --- |
| `notes_updated`<br>Note: Notes file changed — non-empty line count updated | `{count: int  # Number of non-empty lines in the notes file}` |
| `summary_updated`<br>Note: AI summary file changed — parsed point count updated | `{count: int  # Number of parsed bullet-point objects in ai-summary.md}` |

## Feature: Feedback

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Participant Feedback<br>Participant feedback submitted from floating feedback modal.<br>`POST /api/participant/misc/feedback` | `text: string`<br>`participant_name?: string \| null` | `any` |

## Feature: Transcription

### Participant WS
| Message | Payload |
| --- | --- |
| `transcription_language_pending`<br>Note: Daemon detected a transcription language change | `{language: string}` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Set Transcription Language<br>Host sets the transcription language — stores pending request for daemon/macos-addons.<br>Accepted values: ro, en, auto.<br>`POST /api/transcription-language` | `{language: string}` | `any` |
| Poll Transcription Language Request<br>Daemon/macos-addons polls for a pending language change request (clears on read).<br>Consumes and clears the pending transcription language request.<br>`GET /api/transcription-language/request` | - | `any` |

## Feature: Cross-cutting: Reload

### Participant WS
| Message | Payload |
| --- | --- |
| `reload`<br>Note: Daemon synced static files — browser should reload<br>Note: Client should trigger full page reload to pick up new static assets. | - |

### Host WS
| Message | Payload |
| --- | --- |
| `reload`<br>Note: Daemon synced static files — browser should reload<br>Note: Host client should trigger full page reload to pick up new static assets. | - |
