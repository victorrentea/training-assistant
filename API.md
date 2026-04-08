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
| Get Log Level<br>`GET /api/log-level` | `none` | `{level: 'info' \| 'debug'  # enum: 'info' \| 'debug'}` |
| Set Log Level<br>`POST /api/log-level` | `{level: 'info' \| 'debug'  # enum: 'info' \| 'debug'}` | `{level: 'info' \| 'debug'  # enum: 'info' \| 'debug'}` |
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
- `slides_current`
  - payload: `{type: 'slides_current'  # enum: 'slides_current', slides_current?: SlidesCurrent  # null means no active slide}`
  - note: Host navigated to a new slide
- `slides_cache_status`
  - payload: `{type: 'slides_cache_status'  # enum: 'slides_cache_status'}`
  - note: Invalidation signal — participant must call GET /api/slides to refresh
  - note: Client must refetch slide list; payload intentionally carries no cache map.

### Host WS
- `slides_cache_status`
  - payload: `{type: 'slides_cache_status'  # enum: 'slides_cache_status'}`
  - note: Invalidation signal — host must call GET /api/slides to refresh
  - note: Host should refetch slides list; payload intentionally carries no cache map.

## Feature: Activity Switching

### Participant WS
- `activity_updated`
  - payload: `{type: 'activity_updated'  # enum: 'activity_updated', current_activity: 'none' | 'poll' | 'wordcloud' | 'qa' | 'codereview' | 'debate'  # enum: 'none' | 'poll' | 'wordcloud' | 'qa' | 'codereview' | 'debate'}`
  - note: Current activity type changed by host

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
- `participant_count_updated`
  - payload: `{type: 'participant_count_updated'  # enum: 'participant_count_updated', count: int}`
  - note: Participant count changed

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Host State<br>`GET /api/{session_id}/host/state` | `none` | `any`<br>Note: Return full state for host page load — replicates Railway build_for_host().<br>Note: Returns host-facing full state snapshot. |

### Host WS
- `participant_list_updated`
  - payload: `{type: 'participant_list_updated'  # enum: 'participant_list_updated', participants: list[HostParticipant]}`
  - note: Participant list changed (join/register/rename/location) — sent by daemon directly

## Feature: Poll

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Cast Vote<br>`POST /api/participant/poll/vote` | `{option_ids: list[string]}` | `any`<br>Note: Participant casts a vote.<br>Note: Votes are final once submitted; re-vote is rejected. |

### Participant WS
- `poll_opened`
  - payload: `{type: 'poll_opened'  # enum: 'poll_opened', poll: Poll}`
  - note: Poll opened for voting
  - note: Participants can vote only while poll is open.
- `poll_closed`
  - payload: `{type: 'poll_closed'  # enum: 'poll_closed', vote_counts: dict[str, int]  # option_id → vote count, total_votes: int}`
  - note: Voting closed by host
- `poll_correct_revealed`
  - payload: `{type: 'poll_correct_revealed'  # enum: 'poll_correct_revealed', correct_ids: list[string]}`
  - note: Host revealed correct answers
- `poll_cleared`
  - payload: `{type: 'poll_cleared'  # enum: 'poll_cleared'}`
  - note: Poll removed by host
- `poll_timer_started`
  - payload: `{type: 'poll_timer_started'  # enum: 'poll_timer_started', seconds: int}`
  - note: Host started a countdown timer for the poll

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
- `poll_ai_generated`
  - payload: `{type: 'poll_ai_generated'  # enum: 'poll_ai_generated', poll: dict  # Poll data {id, question, options[], multi}}`
  - note: Host-only notification when a new poll is created (before opening)
- `vote_update`
  - payload: `{type: 'vote_update'  # enum: 'vote_update', votes: dict[str, int]  # option_id → vote count}`
  - note: Real-time vote tally while poll is open
  - note: Host-only event; participants do not receive live vote tallies.

## Feature: Word Cloud

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Submit Word<br>`POST /api/participant/wordcloud/word` | `{word: string}` | `any`<br>Note: Participant submits a word to the word cloud. |

### Participant WS
- `wordcloud_updated`
  - payload: `{type: 'wordcloud_updated'  # enum: 'wordcloud_updated', words: dict[str, int]  # word → count, word_order: list[string]  # Newest-first insertion order, topic: string}`
  - note: Word cloud state changed (new word or topic update)

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Clear Wordcloud<br>`POST /api/{session_id}/host/wordcloud/clear` | `none` | `any`<br>Note: Host clears the word cloud. |
| Set Topic<br>`POST /api/{session_id}/host/wordcloud/topic` | `{topic: string}` | `any`<br>Note: Host sets the word cloud topic. |
| Host Submit Word<br>`POST /api/{session_id}/host/wordcloud/word` | `{word: string}` | `any`<br>Note: Host submits a word — same as participant but no scoring. |

### Host WS
- `wordcloud_updated`
  - payload: `{type: 'wordcloud_updated'  # enum: 'wordcloud_updated', words: dict[str, int]  # word → count, word_order: list[string]  # Words ordered newest first, topic: string}`
  - note: Word cloud updated (same payload as participant)

## Feature: Q&A

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Submit Question<br>`POST /api/participant/qa/submit` | `{text: string}` | `any`<br>Note: Participant submits a Q&A question. |
| Upvote Question<br>`POST /api/participant/qa/upvote` | `{question_id: string}` | `any`<br>Note: Participant upvotes a Q&A question. |

### Participant WS
- `qa_updated`
  - payload: `{type: 'qa_updated'  # enum: 'qa_updated', questions: list[QAQuestion]}`
  - note: Q&A list changed (new question, upvote, edit, delete)

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Clear Qa<br>`POST /api/{session_id}/host/qa/clear` | `none` | `any`<br>Note: Host clears all Q&A questions. |
| Delete Question<br>`DELETE /api/{session_id}/host/qa/question/{question_id}` | `none` | `any`<br>Note: Host deletes a question. |
| Toggle Answered<br>`PUT /api/{session_id}/host/qa/question/{question_id}/answered` | `{answered?: bool}` | `any`<br>Note: Host toggles a question's answered flag. |
| Edit Question Text<br>`PUT /api/{session_id}/host/qa/question/{question_id}/text` | `{text: string}` | `any`<br>Note: Host edits a question's text. |
| Host Submit Question<br>`POST /api/{session_id}/host/qa/submit` | `{text: string}` | `any`<br>Note: Host submits a Q&A question — no scoring. |

### Host WS
- `qa_updated`
  - payload: `{type: 'qa_updated'  # enum: 'qa_updated', questions: list[QAQuestion]}`
  - note: Q&A list changed (same structure as participant)

## Feature: Code Review

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Update Selection<br>`PUT /api/participant/codereview/selection` | `{lines?: list[int]}` | `any`<br>Note: Participant sets their selected lines (full replacement). |

### Participant WS
- `codereview_opened`
  - payload: `{type: 'codereview_opened'  # enum: 'codereview_opened', snippet: string, language: string | null}`
  - note: Host opened a code snippet for review
- `codereview_selection_closed`
  - payload: `{type: 'codereview_selection_closed'  # enum: 'codereview_selection_closed'}`
  - note: Host closed the line selection phase
- `codereview_line_confirmed`
  - payload: `{type: 'codereview_line_confirmed'  # enum: 'codereview_line_confirmed', line: int}`
  - note: Host confirmed a line as problematic
- `codereview_cleared`
  - payload: `{type: 'codereview_cleared'  # enum: 'codereview_cleared'}`
  - note: Code review removed by host

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Clear Codereview<br>`DELETE /api/{session_id}/host/codereview` | `none` | `any`<br>Note: Host clears the code review. |
| Create Codereview<br>`POST /api/{session_id}/host/codereview` | `{snippet: string, language?: string \| null, smart_paste?: bool}` | `any`<br>Note: Host creates a code review session. |
| Confirm Line<br>`PUT /api/{session_id}/host/codereview/confirm-line` | `{line: int}` | `any`<br>Note: Host confirms a line as problematic and awards points. |
| Set Codereview Status<br>`PUT /api/{session_id}/host/codereview/status` | `{open?: bool}` | `any`<br>Note: Host closes the selection phase. |

### Host WS
- `codereview_selections_updated`
  - payload: `{type: 'codereview_selections_updated'  # enum: 'codereview_selections_updated', line_counts: dict[str, int]  # line number → count of participants who selected it}`
  - note: Aggregated line selection counts (host-only)

## Feature: Debate

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Submit Argument<br>`POST /api/participant/debate/argument` | `{text: string}` | `any`<br>Note: Participant submits a debate argument. |
| Pick Side<br>`POST /api/participant/debate/pick-side` | `{side: string}` | `any`<br>Note: Participant picks a side (for/against). |
| Upvote Argument<br>`POST /api/participant/debate/upvote` | `{argument_id: string}` | `any`<br>Note: Participant upvotes a debate argument. |
| Volunteer Champion<br>`POST /api/participant/debate/volunteer` | `none` | `any`<br>Note: Participant volunteers as champion for their side. |

### Participant WS
- `debate_updated`
  - payload: `{type: 'debate_updated'  # enum: 'debate_updated', statement?: string | null, phase?: null | 'side_selection' | 'arguments' | 'ai_cleanup' | 'prep' | 'live_debate' | 'ended' | null  # enum: null | 'side_selection' | 'arguments' | 'ai_cleanup' | 'prep' | 'live_debate' | 'ended', sides?: dict[str, string]  # uuid → "for"|"against", arguments?: list[DebateArgument], champions?: dict[str, string]  # "for"|"against" → uuid, auto_assigned?: list[string], first_side?: string | null, round_index?: int | null, round_timer_seconds?: int | null, round_timer_started_at?: string | null}`
  - note: Full debate state snapshot
- `debate_timer`
  - payload: `{type: 'debate_timer'  # enum: 'debate_timer', round_index: int, seconds: int, started_at: string}`
  - note: A timed debate round started
- `debate_round_ended`
  - payload: `{type: 'debate_round_ended'  # enum: 'debate_round_ended'}`
  - note: Current debate round ended

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
- `scores_updated`
  - payload: `{type: 'scores_updated'  # enum: 'scores_updated', scores: dict[str, int]  # uuid → score (all participants)}`
  - note: One or more participants' scores changed
- `leaderboard_revealed`
  - payload: `{type: 'leaderboard_revealed'  # enum: 'leaderboard_revealed', positions: list[LeaderboardPosition]}`
  - note: Leaderboard overlay shown with top positions

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Hide Leaderboard<br>`POST /api/{session_id}/host/leaderboard/hide` | `none` | `any` |
| Show Leaderboard<br>`POST /api/{session_id}/host/leaderboard/show` | `none` | `any` |
| Reset Scores<br>`DELETE /api/{session_id}/host/scores` | `none` | `any` |

### Host WS
- `leaderboard_revealed`
  - payload: `{type: 'leaderboard_revealed'  # enum: 'leaderboard_revealed', positions: list[LeaderboardPosition]}`
  - note: Leaderboard revealed (same payload as participant)

## Feature: Emoji Reactions

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Emoji Reaction<br>`POST /api/participant/emoji/reaction` | `{emoji: string}` | `any`<br>Note: Participant sends an emoji reaction. |

### Host WS
- `emoji_reaction`
  - payload: `{type: 'emoji_reaction'  # enum: 'emoji_reaction', emoji: string}`
  - note: Participant sent an emoji reaction — floating animation on host screen

## Feature: Quiz Generation

### Participant WS
- `quiz_status`
  - payload: `{type: 'quiz_status'  # enum: 'quiz_status', status: string  # "generating"|"ready"|"error", message: string}`
  - note: Quiz generation progress update
- `quiz_preview`
  - payload: `{type: 'quiz_preview'  # enum: 'quiz_preview', quiz?: any | null  # Set to null to clear the preview, question?: string, options?: list[string], multi?: bool, correct_indices?: list[int]}`
  - note: Quiz preview for host review before publishing (quiz=null to clear)

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Clear Quiz Preview<br>`DELETE /api/{session_id}/host/quiz-preview` | `none` | `any`<br>Note: Host clears the current quiz preview. |
| Request Quiz Refine<br>`POST /api/{session_id}/host/quiz-refine` | `{target: string, preview?: any \| null}` | `any`<br>Note: Host requests regeneration of a specific question or option. |
| Request Quiz<br>`POST /api/{session_id}/host/quiz-request` | `{minutes?: int \| null, topic?: string \| null}` | `any`<br>Note: Host requests a quiz — stores request for the orchestrator loop to pick up. |
| Get Quiz Md<br>`GET /api/{session_id}/quiz-md` | `none` | `any`<br>Note: Return the accumulated quiz markdown history. |

### Host WS
- `quiz_status`
  - payload: `{type: 'quiz_status'  # enum: 'quiz_status', status: string  # "generating" | "ready" | "error", message?: string}`
  - note: Quiz generation progress update
- `quiz_preview`
  - payload: `{type: 'quiz_preview'  # enum: 'quiz_preview', quiz?: any | null  # Set to null to clear the preview, question?: string, options?: list[object], multi?: bool, correct_indices?: list[int]}`
  - note: Generated quiz ready for host review (quiz=null to clear)

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
- `paste_received`
  - payload: `{type: 'paste_received'  # enum: 'paste_received', uuid: string  # Participant UUID who submitted the paste, id: string  # Paste ID, text: string}`
  - note: Participant submitted a text paste
- `file_uploaded`
  - payload: `{type: 'file_uploaded'  # enum: 'file_uploaded', uuid: string  # Participant UUID who uploaded the file, id: string  # File ID, filename: string, size: int  # File size in bytes, disk_path: string  # Absolute path on the host's disk where the file was saved by the daemon}`
  - note: Participant uploaded a file (daemon has downloaded it to session folder)

## Feature: Notes & Summary

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Notes<br>`GET /api/participant/notes` | `none` | `any`<br>Note: Get session notes content. |
| Get Summary<br>`GET /api/participant/summary` | `none` | `any`<br>Note: Get summary points and raw markdown. |

### Participant WS
- `notes_updated`
  - payload: `{type: 'notes_updated'  # enum: 'notes_updated', count: int  # Number of non-empty lines in the notes file}`
  - note: Notes file changed — non-empty line count updated
- `summary_updated`
  - payload: `{type: 'summary_updated'  # enum: 'summary_updated', count: int  # Number of parsed bullet-point objects in ai-summary.md}`
  - note: AI summary file changed — parsed point count updated

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Host Notes<br>`GET /api/{session_id}/host/notes` | `none` | `any`<br>Note: Return current session notes content. |
| Get Host Summary<br>`GET /api/{session_id}/host/summary` | `none` | `any`<br>Note: Return summary points, raw markdown, and updated_at timestamp. |

### Host WS
- `notes_updated`
  - payload: `{type: 'notes_updated'  # enum: 'notes_updated', count: int  # Number of non-empty lines in the notes file}`
  - note: Notes file changed — non-empty line count updated
- `summary_updated`
  - payload: `{type: 'summary_updated'  # enum: 'summary_updated', count: int  # Number of parsed bullet-point objects in ai-summary.md}`
  - note: AI summary file changed — parsed point count updated

## Feature: Feedback

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Participant Feedback<br>`POST /api/participant/misc/feedback` | `{text: string, participant_name?: string \| null}` | `any`<br>Note: Participant feedback submitted from floating feedback modal. |

## Feature: Transcription

### Participant WS
- `transcription_language_pending`
  - payload: `{type: 'transcription_language_pending'  # enum: 'transcription_language_pending', language: string}`
  - note: Daemon detected a transcription language change

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Set Transcription Language<br>`POST /api/transcription-language` | `{language: string}` | `any`<br>Note: Host sets the transcription language — stores pending request for daemon/macos-addons.<br>Note: Accepted values: ro, en, auto. |
| Poll Transcription Language Request<br>`GET /api/transcription-language/request` | `none` | `any`<br>Note: Daemon/macos-addons polls for a pending language change request (clears on read).<br>Note: Consumes and clears the pending transcription language request. |

## Feature: Cross-cutting: Reload

### Participant WS
- `reload`
  - payload: `{type: 'reload'  # enum: 'reload'}`
  - note: Daemon synced static files — browser should reload
  - note: Client should trigger full page reload to pick up new static assets.

### Host WS
- `reload`
  - payload: `{type: 'reload'  # enum: 'reload'}`
  - note: Daemon synced static files — browser should reload
  - note: Host client should trigger full page reload to pick up new static assets.
