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
| Daemon Status<br>`GET /api/daemon-status` | `none` | `any` |
| Get Log Level<br>`GET /api/log-level` | `none` | `{level: 'info' \| 'debug'}` |
| Set Log Level<br>`POST /api/log-level` | `{level: 'info' \| 'debug'}` | `{level: 'info' \| 'debug'}` |
| Get Session Active<br>`GET /api/session/active` | `none` | `any`<br>Note: Public endpoint: returns the active session_id or null. |
| End Session<br>`POST /api/session/end` | `none` | `any`<br>Note: Host ends the current session. Railway closes WS connections on session end. |
| End Talk<br>`POST /api/session/end_talk` | `none` | `any`<br>Note: Host ends the nested talk. |
| List Session Folders<br>`GET /api/session/folders` | `none` | `any`<br>Note: List available session folders. |
| Resume Session<br>`POST /api/session/resume` | `{folder: string}` | `any`<br>Note: Host resumes an existing session folder. Uses session-state.json as persisted storage. |
| Start Session<br>`POST /api/session/start` | `{name: string, type?: string}` | `any`<br>Note: Host starts a new session (creates folder, assigns session_id, clean slate). |
| Start Talk<br>`POST /api/session/start_talk` | `none` | `any`<br>Note: Host starts a nested talk (conference mode). |
| Set Mode<br>`POST /api/{session_id}/host/mode` | `{mode: string}` | `any`<br>Note: Host switches session mode (workshop/conference). |
| Get Interval Lines Txt<br>`GET /api/{session_id}/session/interval-lines.txt` | `none` | `text/plain: string`<br>Note: Return raw transcript lines for a time window.<br>Note: Returns text/plain interval lines for session export/inspection. |

## Feature: Slides

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Slides Cache Status<br>`GET /api/participant/slides-cache-status` | `none` | `any`<br>Note: Get slides cache status.<br>Note: Primarily for diagnostics; UI cache invalidation is event-driven via slides_cache_status WS. |

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
| Set Activity<br>`POST /api/{session_id}/host/activity` | `{activity: string}` | `any`<br>Note: Host switches the current activity. |
| Set Activity<br>`PUT /api/{session_id}/host/activity` | `{activity: string}` | `any`<br>Note: Host switches the current activity. |

## Feature: Identity

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Refresh Avatar Endpoint<br>`POST /api/participant/avatar` | `{rejected?: list[string]}` | `{ok?: bool, avatar: string}`<br>Note: Re-roll avatar (conference mode only). |
| Set Location<br>`POST /api/participant/location` | `{location: string}` | `{ok?: bool}`<br>Note: Store participant city/timezone. |
| Rename Participant<br>`PUT /api/participant/name` | `{name: string}` | -<br>Note: Rename a registered participant. Returns 400 if not yet registered. |
| Register Participant<br>`POST /api/participant/register` | `none` | `{name: string, avatar: string}`<br>Note: Register participant — assign name+avatar. Idempotent for returning participants. |
| Get Participant State<br>`GET /api/participant/state` | `none` | `any`<br>Note: Return full personalised state for a participant — used on page load and WS reconnect.<br>Note: Returns participant-personalized full state snapshot. |

### Participant WS
| Message | Payload |
| --- | --- |
| `participant_count_updated`<br>Note: Participant count changed | `{count: int}` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Host State<br>`GET /api/{session_id}/host/state` | `none` | `any`<br>Note: Return full state for host page load — replicates Railway build_for_host().<br>Note: Returns host-facing full state snapshot. |

### Host WS
| Message | Payload |
| --- | --- |
| `participant_list_updated`<br>Note: Participant list changed (join/register/rename/location) — sent by daemon directly | `{participants: list[HostParticipant]}` |

## Feature: Poll

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Cast Vote<br>`POST /api/participant/poll/vote` | `{option_ids: list[string]}` | `any`<br>Note: Participant casts a vote.<br>Note: Votes are final once submitted; re-vote is rejected. |

### Participant WS
| Message | Payload |
| --- | --- |
| `poll_opened`<br>Note: Poll opened for voting<br>Note: Participants can vote only while poll is open. | `{poll: Poll}` |
| `poll_closed`<br>Note: Voting closed by host | `{vote_counts: dict[str, int]  # option_id → vote count, total_votes: int}` |
| `poll_correct_revealed`<br>Note: Host revealed correct answers | `{correct_ids: list[string]}` |
| `poll_cleared`<br>Note: Poll removed by host | - |
| `poll_timer_started`<br>Note: Host started a countdown timer for the poll | `{seconds: int}` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Delete Poll<br>`DELETE /api/{session_id}/host/poll` | `none` | `any`<br>Note: Host deletes the current poll. |
| Create Poll<br>`POST /api/{session_id}/host/poll` | `{question?: string, options?: list[dict[str, any]], multi?: bool, correct_count?: int \| null}` | `any`<br>Note: Host creates a new poll. |
| Close Poll<br>`POST /api/{session_id}/host/poll/close` | `none` | `any`<br>Note: Host closes the poll. |
| Reveal Correct<br>`PUT /api/{session_id}/host/poll/correct` | `{correct_ids?: list[string]}` | `any`<br>Note: Host reveals correct answers and awards scores. |
| Open Poll<br>`POST /api/{session_id}/host/poll/open` | `none` | `any`<br>Note: Host opens the poll for voting. |
| Set Poll Status<br>`PUT /api/{session_id}/host/poll/status` | `{open: bool}` | `any`<br>Note: Compatibility: {open: true} → open_poll, {open: false} → close_poll. |
| Start Timer<br>`POST /api/{session_id}/host/poll/timer` | `{seconds?: int}` | `any`<br>Note: Host starts a countdown timer for the poll. |

### Host WS
| Message | Payload |
| --- | --- |
| `poll_ai_generated`<br>Note: Host-only notification when a new poll is created (before opening) | `{poll: dict  # Poll data {id, question, options[], multi}}` |
| `vote_update`<br>Note: Real-time vote tally while poll is open<br>Note: Host-only event; participants do not receive live vote tallies. | `{votes: dict[str, int]  # option_id → vote count}` |

## Feature: Word Cloud

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Submit Word<br>`POST /api/participant/wordcloud/word` | `{word: string}` | `any`<br>Note: Participant submits a word to the word cloud. |

### Participant WS
| Message | Payload |
| --- | --- |
| `wordcloud_updated`<br>Note: Word cloud state changed (new word or topic update) | `{words: dict[str, int]  # word → count, word_order: list[string]  # Newest-first insertion order, topic: string}` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Clear Wordcloud<br>`POST /api/{session_id}/host/wordcloud/clear` | `none` | `any`<br>Note: Host clears the word cloud. |
| Set Topic<br>`POST /api/{session_id}/host/wordcloud/topic` | `{topic: string}` | `any`<br>Note: Host sets the word cloud topic. |
| Host Submit Word<br>`POST /api/{session_id}/host/wordcloud/word` | `{word: string}` | `any`<br>Note: Host submits a word — same as participant but no scoring. |

### Host WS
| Message | Payload |
| --- | --- |
| `wordcloud_updated`<br>Note: Word cloud updated (same payload as participant) | `{words: dict[str, int]  # word → count, word_order: list[string]  # Words ordered newest first, topic: string}` |

## Feature: Q&A

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Submit Question<br>`POST /api/participant/qa/submit` | `{text: string}` | `any`<br>Note: Participant submits a Q&A question. |
| Upvote Question<br>`POST /api/participant/qa/upvote` | `{question_id: string}` | `any`<br>Note: Participant upvotes a Q&A question. |

### Participant WS
| Message | Payload |
| --- | --- |
| `qa_updated`<br>Note: Q&A list changed (new question, upvote, edit, delete) | `{questions: list[QAQuestion]}` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Clear Qa<br>`POST /api/{session_id}/host/qa/clear` | `none` | `any`<br>Note: Host clears all Q&A questions. |
| Delete Question<br>`DELETE /api/{session_id}/host/qa/question/{question_id}` | `none` | `any`<br>Note: Host deletes a question. |
| Toggle Answered<br>`PUT /api/{session_id}/host/qa/question/{question_id}/answered` | `{answered?: bool}` | `any`<br>Note: Host toggles a question's answered flag. |
| Edit Question Text<br>`PUT /api/{session_id}/host/qa/question/{question_id}/text` | `{text: string}` | `any`<br>Note: Host edits a question's text. |
| Host Submit Question<br>`POST /api/{session_id}/host/qa/submit` | `{text: string}` | `any`<br>Note: Host submits a Q&A question — no scoring. |

### Host WS
| Message | Payload |
| --- | --- |
| `qa_updated`<br>Note: Q&A list changed (same structure as participant) | `{questions: list[QAQuestion]}` |

## Feature: Code Review

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Update Selection<br>`PUT /api/participant/codereview/selection` | `{lines?: list[int]}` | `any`<br>Note: Participant sets their selected lines (full replacement). |

### Participant WS
| Message | Payload |
| --- | --- |
| `codereview_opened`<br>Note: Host opened a code snippet for review | `{snippet: string, language: string \| null}` |
| `codereview_selection_closed`<br>Note: Host closed the line selection phase | - |
| `codereview_line_confirmed`<br>Note: Host confirmed a line as problematic | `{line: int}` |
| `codereview_cleared`<br>Note: Code review removed by host | - |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Clear Codereview<br>`DELETE /api/{session_id}/host/codereview` | `none` | `any`<br>Note: Host clears the code review. |
| Create Codereview<br>`POST /api/{session_id}/host/codereview` | `{snippet: string, language?: string \| null, smart_paste?: bool}` | `any`<br>Note: Host creates a code review session. |
| Confirm Line<br>`PUT /api/{session_id}/host/codereview/confirm-line` | `{line: int}` | `any`<br>Note: Host confirms a line as problematic and awards points. |
| Set Codereview Status<br>`PUT /api/{session_id}/host/codereview/status` | `{open?: bool}` | `any`<br>Note: Host closes the selection phase. |

### Host WS
| Message | Payload |
| --- | --- |
| `codereview_selections_updated`<br>Note: Aggregated line selection counts (host-only) | `{line_counts: dict[str, int]  # line number → count of participants who selected it}` |

## Feature: Debate

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Submit Argument<br>`POST /api/participant/debate/argument` | `{text: string}` | `any`<br>Note: Participant submits a debate argument. |
| Pick Side<br>`POST /api/participant/debate/pick-side` | `{side: string}` | `any`<br>Note: Participant picks a side (for/against). |
| Upvote Argument<br>`POST /api/participant/debate/upvote` | `{argument_id: string}` | `any`<br>Note: Participant upvotes a debate argument. |
| Volunteer Champion<br>`POST /api/participant/debate/volunteer` | `none` | `any`<br>Note: Participant volunteers as champion for their side. |

### Participant WS
| Message | Payload |
| --- | --- |
| `debate_updated`<br>Note: Full debate state snapshot | `{statement?: string \| null, phase?: null \| 'side_selection' \| 'arguments' \| 'ai_cleanup' \| 'prep' \| 'live_debate' \| 'ended' \| null, sides?: dict[str, string]  # uuid → "for"\|"against", arguments?: list[DebateArgument], champions?: dict[str, string]  # "for"\|"against" → uuid, auto_assigned?: list[string], first_side?: string \| null, round_index?: int \| null, round_timer_seconds?: int \| null, round_timer_started_at?: string \| null}` |
| `debate_timer`<br>Note: A timed debate round started | `{round_index: int, seconds: int, started_at: string}` |
| `debate_round_ended`<br>Note: Current debate round ended | - |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Launch Debate<br>`POST /api/{session_id}/host/debate` | `{statement: string}` | `any`<br>Note: Host launches a debate with a statement. |
| Receive Ai Result<br>`POST /api/{session_id}/host/debate/ai-result` | `{merges?: list[any], cleaned?: list[any], new_arguments?: list[any]}` | `any`<br>Note: Manual/skip AI result — host posts AI cleanup results directly. |
| Close Selection<br>`POST /api/{session_id}/host/debate/close-selection` | `none` | `any`<br>Note: Host closes side selection; auto-assigns remaining participants. |
| End Arguments<br>`POST /api/{session_id}/host/debate/end-arguments` | `none` | `any`<br>Note: Host ends arguments phase; triggers AI cleanup in background. |
| End Round<br>`POST /api/{session_id}/host/debate/end-round` | `none` | `any`<br>Note: Host ends the current round early. |
| Set First Side<br>`POST /api/{session_id}/host/debate/first-side` | `{side: string}` | `any`<br>Note: Host picks which side speaks first in live debate. |
| Force Assign<br>`POST /api/{session_id}/host/debate/force-assign` | `none` | `any`<br>Note: Host force-assigns all unassigned participants. |
| Advance Phase<br>`POST /api/{session_id}/host/debate/phase` | `{phase: string}` | `any`<br>Note: Host advances the debate to a specific phase. |
| Reset Debate<br>`POST /api/{session_id}/host/debate/reset` | `none` | `any`<br>Note: Host resets all debate state. |
| Start Round Timer<br>`POST /api/{session_id}/host/debate/round-timer` | `{round_index: int, seconds: int}` | `any`<br>Note: Host starts a timed round. |

## Feature: Scores & Leaderboard

### Participant WS
| Message | Payload |
| --- | --- |
| `scores_updated`<br>Note: One or more participants' scores changed | `{scores: dict[str, int]  # uuid → score (all participants)}` |
| `leaderboard_revealed`<br>Note: Leaderboard overlay shown with top positions | `{positions: list[LeaderboardPosition]}` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Hide Leaderboard<br>`POST /api/{session_id}/host/leaderboard/hide` | `none` | `any` |
| Show Leaderboard<br>`POST /api/{session_id}/host/leaderboard/show` | `none` | `any` |
| Reset Scores<br>`DELETE /api/{session_id}/host/scores` | `none` | `any` |

### Host WS
| Message | Payload |
| --- | --- |
| `leaderboard_revealed`<br>Note: Leaderboard revealed (same payload as participant) | `{positions: list[LeaderboardPosition]}` |

## Feature: Emoji Reactions

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Emoji Reaction<br>`POST /api/participant/emoji/reaction` | `{emoji: string}` | `any`<br>Note: Participant sends an emoji reaction. |

### Host WS
| Message | Payload |
| --- | --- |
| `emoji_reaction`<br>Note: Participant sent an emoji reaction — floating animation on host screen | `{emoji: string}` |

## Feature: Quiz Generation

### Participant WS
| Message | Payload |
| --- | --- |
| `quiz_status`<br>Note: Quiz generation progress update | `{status: string  # "generating"\|"ready"\|"error", message: string}` |
| `quiz_preview`<br>Note: Quiz preview for host review before publishing (quiz=null to clear) | `{quiz?: any \| null  # Set to null to clear the preview, question?: string, options?: list[string], multi?: bool, correct_indices?: list[int]}` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Clear Quiz Preview<br>`DELETE /api/{session_id}/host/quiz-preview` | `none` | `any`<br>Note: Host clears the current quiz preview. |
| Request Quiz Refine<br>`POST /api/{session_id}/host/quiz-refine` | `{target: string, preview?: any \| null}` | `any`<br>Note: Host requests regeneration of a specific question or option. |
| Request Quiz<br>`POST /api/{session_id}/host/quiz-request` | `{minutes?: int \| null, topic?: string \| null}` | `any`<br>Note: Host requests a quiz — stores request for the orchestrator loop to pick up. |
| Get Quiz Md<br>`GET /api/{session_id}/quiz-md` | `none` | `any`<br>Note: Return the accumulated quiz markdown history. |

### Host WS
| Message | Payload |
| --- | --- |
| `quiz_status`<br>Note: Quiz generation progress update | `{status: string  # "generating" \| "ready" \| "error", message?: string}` |
| `quiz_preview`<br>Note: Generated quiz ready for host review (quiz=null to clear) | `{quiz?: any \| null  # Set to null to clear the preview, question?: string, options?: list[object], multi?: bool, correct_indices?: list[int]}` |

## Feature: Paste & File Upload

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Paste Text<br>`POST /api/participant/paste` | `{text: string}` | `any`<br>Note: Participant pastes text to be seen by host. |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Pastes<br>`GET /api/{session_id}/host/pastes` | `none` | `any`<br>Note: Return all pending paste entries grouped by participant uuid. |
| Mark Uploaded File Seen<br>`POST /api/{session_id}/host/uploads/seen` | `{uuid: string, file_id: string}` | `any`<br>Note: Mark an uploaded-file indicator as seen by host in daemon session state. |

### Host WS
| Message | Payload |
| --- | --- |
| `paste_received`<br>Note: Participant submitted a text paste | `{uuid: string  # Participant UUID who submitted the paste, id: string  # Paste ID, text: string}` |
| `file_uploaded`<br>Note: Participant uploaded a file (daemon has downloaded it to session folder) | `{uuid: string  # Participant UUID who uploaded the file, id: string  # File ID, filename: string, size: int  # File size in bytes, disk_path: string  # Absolute path on the host's disk where the file was saved by the daemon}` |

## Feature: Notes & Summary

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Notes<br>`GET /api/participant/notes` | `none` | `any`<br>Note: Get session notes content. |
| Get Summary<br>`GET /api/participant/summary` | `none` | `any`<br>Note: Get summary points and raw markdown. |

### Participant WS
| Message | Payload |
| --- | --- |
| `notes_updated`<br>Note: Notes file changed — non-empty line count updated | `{count: int  # Number of non-empty lines in the notes file}` |
| `summary_updated`<br>Note: AI summary file changed — parsed point count updated | `{count: int  # Number of parsed bullet-point objects in ai-summary.md}` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Host Notes<br>`GET /api/{session_id}/host/notes` | `none` | `any`<br>Note: Return current session notes content. |
| Get Host Summary<br>`GET /api/{session_id}/host/summary` | `none` | `any`<br>Note: Return summary points, raw markdown, and updated_at timestamp. |

### Host WS
| Message | Payload |
| --- | --- |
| `notes_updated`<br>Note: Notes file changed — non-empty line count updated | `{count: int  # Number of non-empty lines in the notes file}` |
| `summary_updated`<br>Note: AI summary file changed — parsed point count updated | `{count: int  # Number of parsed bullet-point objects in ai-summary.md}` |

## Feature: Feedback

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Participant Feedback<br>`POST /api/participant/misc/feedback` | `{text: string, participant_name?: string \| null}` | `any`<br>Note: Participant feedback submitted from floating feedback modal. |

## Feature: Transcription

### Participant WS
| Message | Payload |
| --- | --- |
| `transcription_language_pending`<br>Note: Daemon detected a transcription language change | `{language: string}` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Set Transcription Language<br>`POST /api/transcription-language` | `{language: string}` | `any`<br>Note: Host sets the transcription language — stores pending request for daemon/macos-addons.<br>Note: Accepted values: ro, en, auto. |
| Poll Transcription Language Request<br>`GET /api/transcription-language/request` | `none` | `any`<br>Note: Daemon/macos-addons polls for a pending language change request (clears on read).<br>Note: Consumes and clears the pending transcription language request. |

## Feature: Cross-cutting: Reload

### Participant WS
| Message | Payload |
| --- | --- |
| `reload`<br>Note: Daemon synced static files — browser should reload<br>Note: Client should trigger full page reload to pick up new static assets. | - |

### Host WS
| Message | Payload |
| --- | --- |
| `reload`<br>Note: Daemon synced static files — browser should reload<br>Note: Host client should trigger full page reload to pick up new static assets. | - |
