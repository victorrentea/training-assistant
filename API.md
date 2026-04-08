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

### Participant REST
- (none)

### Participant WS
- (none)

### Host REST
- `GET /api/daemon-status`
  - request: `none`
  - response: `200: any`
  - note: Daemon Status
- `GET /api/log-level`
  - request: `none`
  - response: `200: {level: 'info' | 'debug'  # enum: 'info' | 'debug'}`
  - note: Get Log Level
- `POST /api/log-level`
  - request: `application/json: {level: 'info' | 'debug'  # enum: 'info' | 'debug'}`
  - response: `200: {level: 'info' | 'debug'  # enum: 'info' | 'debug'}`
  - note: Set Log Level
- `GET /api/session/active`
  - request: `none`
  - response: `200: any`
  - note: Get Session Active
  - note: Public endpoint: returns the active session_id or null.
- `POST /api/session/end`
  - request: `none`
  - response: `200: any`
  - note: End Session
  - note: Host ends the current session. Railway closes WS connections on session end.
- `POST /api/session/end_talk`
  - request: `none`
  - response: `200: any`
  - note: End Talk
  - note: Host ends the nested talk.
- `GET /api/session/folders`
  - request: `none`
  - response: `200: any`
  - note: List Session Folders
  - note: List available session folders.
- `POST /api/session/resume`
  - request: `application/json: {folder: string}`
  - response: `200: any`
  - note: Resume Session
  - note: Host resumes an existing session folder. Uses session-state.json as persisted storage.
- `POST /api/session/start`
  - request: `application/json: {name: string, type?: string}`
  - response: `200: any`
  - note: Start Session
  - note: Host starts a new session (creates folder, assigns session_id, clean slate).
- `POST /api/session/start_talk`
  - request: `none`
  - response: `200: any`
  - note: Start Talk
  - note: Host starts a nested talk (conference mode).
- `POST /api/{session_id}/host/mode`
  - request: `application/json: {mode: string}`
  - response: `200: any`
  - note: Set Mode
  - note: Host switches session mode (workshop/conference).
- `GET /api/{session_id}/session/interval-lines.txt`
  - request: `none`
  - response: `200 (text/plain): string`
  - note: Get Interval Lines Txt
  - note: Return raw transcript lines for a time window.
  - note: Returns text/plain interval lines for session export/inspection.

### Host WS
- (none)

## Feature: Slides

### Participant REST
- `GET /api/participant/slides-cache-status`
  - request: `none`
  - response: `200: any`
  - note: Get Slides Cache Status
  - note: Get slides cache status.
  - note: Primarily for diagnostics; UI cache invalidation is event-driven via slides_cache_status WS.

### Participant WS
- `slides_current`
  - payload: `{type: 'slides_current'  # enum: 'slides_current', slides_current?: SlidesCurrent  # null means no active slide}`
  - note: Host navigated to a new slide
- `slides_cache_status`
  - payload: `{type: 'slides_cache_status'  # enum: 'slides_cache_status'}`
  - note: Invalidation signal — participant must call GET /api/slides to refresh
  - note: Client must refetch slide list; payload intentionally carries no cache map.

### Host REST
- (none)

### Host WS
- `slides_cache_status`
  - payload: `{type: 'slides_cache_status'  # enum: 'slides_cache_status'}`
  - note: Invalidation signal — host must call GET /api/slides to refresh
  - note: Host should refetch slides list; payload intentionally carries no cache map.

## Feature: Activity Switching

### Participant REST
- (none)

### Participant WS
- `activity_updated`
  - payload: `{type: 'activity_updated'  # enum: 'activity_updated', current_activity: 'none' | 'poll' | 'wordcloud' | 'qa' | 'codereview' | 'debate'  # enum: 'none' | 'poll' | 'wordcloud' | 'qa' | 'codereview' | 'debate'}`
  - note: Current activity type changed by host

### Host REST
- `POST /api/{session_id}/host/activity`
  - request: `application/json: {activity: string}`
  - response: `200: any`
  - note: Set Activity
  - note: Host switches the current activity.
- `PUT /api/{session_id}/host/activity`
  - request: `application/json: {activity: string}`
  - response: `200: any`
  - note: Set Activity
  - note: Host switches the current activity.

### Host WS
- (none)

## Feature: Identity

### Participant REST
- `POST /api/participant/avatar`
  - request: `application/json: {rejected?: list[string]}`
  - response: `200: any`
  - note: Refresh Avatar Endpoint
  - note: Re-roll avatar (conference mode only).
- `POST /api/participant/location`
  - request: `application/json: {location: string}`
  - response: `200: any`
  - note: Set Location
  - note: Store participant city/timezone.
- `PUT /api/participant/name`
  - request: `application/json: {name: string}`
  - response: `200: any`
  - note: Rename Participant
  - note: Rename a registered participant. Returns 400 if not yet registered.
- `POST /api/participant/register`
  - request: `none`
  - response: `200: any`
  - note: Register Participant
  - note: Register participant — assign name+avatar. Idempotent for returning participants.
- `GET /api/participant/state`
  - request: `none`
  - response: `200: any`
  - note: Get Participant State
  - note: Return full personalised state for a participant — used on page load and WS reconnect.
  - note: Returns participant-personalized full state snapshot.

### Participant WS
- `participant_count_updated`
  - payload: `{type: 'participant_count_updated'  # enum: 'participant_count_updated', count: int}`
  - note: Participant count changed

### Host REST
- `GET /api/{session_id}/host/state`
  - request: `none`
  - response: `200: any`
  - note: Get Host State
  - note: Return full state for host page load — replicates Railway build_for_host().
  - note: Returns host-facing full state snapshot.

### Host WS
- `participant_list_updated`
  - payload: `{type: 'participant_list_updated'  # enum: 'participant_list_updated', participants: list[HostParticipant]}`
  - note: Participant list changed (join/register/rename/location) — sent by daemon directly

## Feature: Poll

### Participant REST
- `POST /api/participant/poll/vote`
  - request: `application/json: {option_ids: list[string]}`
  - response: `200: any`
  - note: Cast Vote
  - note: Participant casts a vote.
  - note: Votes are final once submitted; re-vote is rejected.

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
- `DELETE /api/{session_id}/host/poll`
  - request: `none`
  - response: `200: any`
  - note: Delete Poll
  - note: Host deletes the current poll.
- `POST /api/{session_id}/host/poll`
  - request: `application/json: {question?: string, options?: list[dict[str, any]], multi?: bool, correct_count?: int | null}`
  - response: `200: any`
  - note: Create Poll
  - note: Host creates a new poll.
- `POST /api/{session_id}/host/poll/close`
  - request: `none`
  - response: `200: any`
  - note: Close Poll
  - note: Host closes the poll.
- `PUT /api/{session_id}/host/poll/correct`
  - request: `application/json: {correct_ids?: list[string]}`
  - response: `200: any`
  - note: Reveal Correct
  - note: Host reveals correct answers and awards scores.
- `POST /api/{session_id}/host/poll/open`
  - request: `none`
  - response: `200: any`
  - note: Open Poll
  - note: Host opens the poll for voting.
- `PUT /api/{session_id}/host/poll/status`
  - request: `application/json: {open: bool}`
  - response: `200: any`
  - note: Set Poll Status
  - note: Compatibility: {open: true} → open_poll, {open: false} → close_poll.
- `POST /api/{session_id}/host/poll/timer`
  - request: `application/json: {seconds?: int}`
  - response: `200: any`
  - note: Start Timer
  - note: Host starts a countdown timer for the poll.

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
- `POST /api/participant/wordcloud/word`
  - request: `application/json: {word: string}`
  - response: `200: any`
  - note: Submit Word
  - note: Participant submits a word to the word cloud.

### Participant WS
- `wordcloud_updated`
  - payload: `{type: 'wordcloud_updated'  # enum: 'wordcloud_updated', words: dict[str, int]  # word → count, word_order: list[string]  # Newest-first insertion order, topic: string}`
  - note: Word cloud state changed (new word or topic update)

### Host REST
- `POST /api/{session_id}/host/wordcloud/clear`
  - request: `none`
  - response: `200: any`
  - note: Clear Wordcloud
  - note: Host clears the word cloud.
- `POST /api/{session_id}/host/wordcloud/topic`
  - request: `application/json: {topic: string}`
  - response: `200: any`
  - note: Set Topic
  - note: Host sets the word cloud topic.
- `POST /api/{session_id}/host/wordcloud/word`
  - request: `application/json: {word: string}`
  - response: `200: any`
  - note: Host Submit Word
  - note: Host submits a word — same as participant but no scoring.

### Host WS
- `wordcloud_updated`
  - payload: `{type: 'wordcloud_updated'  # enum: 'wordcloud_updated', words: dict[str, int]  # word → count, word_order: list[string]  # Words ordered newest first, topic: string}`
  - note: Word cloud updated (same payload as participant)

## Feature: Q&A

### Participant REST
- `POST /api/participant/qa/submit`
  - request: `application/json: {text: string}`
  - response: `200: any`
  - note: Submit Question
  - note: Participant submits a Q&A question.
- `POST /api/participant/qa/upvote`
  - request: `application/json: {question_id: string}`
  - response: `200: any`
  - note: Upvote Question
  - note: Participant upvotes a Q&A question.

### Participant WS
- `qa_updated`
  - payload: `{type: 'qa_updated'  # enum: 'qa_updated', questions: list[QAQuestion]}`
  - note: Q&A list changed (new question, upvote, edit, delete)

### Host REST
- `POST /api/{session_id}/host/qa/clear`
  - request: `none`
  - response: `200: any`
  - note: Clear Qa
  - note: Host clears all Q&A questions.
- `DELETE /api/{session_id}/host/qa/question/{question_id}`
  - request: `none`
  - response: `200: any`
  - note: Delete Question
  - note: Host deletes a question.
- `PUT /api/{session_id}/host/qa/question/{question_id}/answered`
  - request: `application/json: {answered?: bool}`
  - response: `200: any`
  - note: Toggle Answered
  - note: Host toggles a question's answered flag.
- `PUT /api/{session_id}/host/qa/question/{question_id}/text`
  - request: `application/json: {text: string}`
  - response: `200: any`
  - note: Edit Question Text
  - note: Host edits a question's text.
- `POST /api/{session_id}/host/qa/submit`
  - request: `application/json: {text: string}`
  - response: `200: any`
  - note: Host Submit Question
  - note: Host submits a Q&A question — no scoring.

### Host WS
- `qa_updated`
  - payload: `{type: 'qa_updated'  # enum: 'qa_updated', questions: list[QAQuestion]}`
  - note: Q&A list changed (same structure as participant)

## Feature: Code Review

### Participant REST
- `PUT /api/participant/codereview/selection`
  - request: `application/json: {lines?: list[int]}`
  - response: `200: any`
  - note: Update Selection
  - note: Participant sets their selected lines (full replacement).

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
- `DELETE /api/{session_id}/host/codereview`
  - request: `none`
  - response: `200: any`
  - note: Clear Codereview
  - note: Host clears the code review.
- `POST /api/{session_id}/host/codereview`
  - request: `application/json: {snippet: string, language?: string | null, smart_paste?: bool}`
  - response: `200: any`
  - note: Create Codereview
  - note: Host creates a code review session.
- `PUT /api/{session_id}/host/codereview/confirm-line`
  - request: `application/json: {line: int}`
  - response: `200: any`
  - note: Confirm Line
  - note: Host confirms a line as problematic and awards points.
- `PUT /api/{session_id}/host/codereview/status`
  - request: `application/json: {open?: bool}`
  - response: `200: any`
  - note: Set Codereview Status
  - note: Host closes the selection phase.

### Host WS
- `codereview_selections_updated`
  - payload: `{type: 'codereview_selections_updated'  # enum: 'codereview_selections_updated', line_counts: dict[str, int]  # line number → count of participants who selected it}`
  - note: Aggregated line selection counts (host-only)

## Feature: Debate

### Participant REST
- `POST /api/participant/debate/argument`
  - request: `application/json: {text: string}`
  - response: `200: any`
  - note: Submit Argument
  - note: Participant submits a debate argument.
- `POST /api/participant/debate/pick-side`
  - request: `application/json: {side: string}`
  - response: `200: any`
  - note: Pick Side
  - note: Participant picks a side (for/against).
- `POST /api/participant/debate/upvote`
  - request: `application/json: {argument_id: string}`
  - response: `200: any`
  - note: Upvote Argument
  - note: Participant upvotes a debate argument.
- `POST /api/participant/debate/volunteer`
  - request: `none`
  - response: `200: any`
  - note: Volunteer Champion
  - note: Participant volunteers as champion for their side.

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
- `POST /api/{session_id}/host/debate`
  - request: `application/json: {statement: string}`
  - response: `200: any`
  - note: Launch Debate
  - note: Host launches a debate with a statement.
- `POST /api/{session_id}/host/debate/ai-result`
  - request: `application/json: {merges?: list[any], cleaned?: list[any], new_arguments?: list[any]}`
  - response: `200: any`
  - note: Receive Ai Result
  - note: Manual/skip AI result — host posts AI cleanup results directly.
- `POST /api/{session_id}/host/debate/close-selection`
  - request: `none`
  - response: `200: any`
  - note: Close Selection
  - note: Host closes side selection; auto-assigns remaining participants.
- `POST /api/{session_id}/host/debate/end-arguments`
  - request: `none`
  - response: `200: any`
  - note: End Arguments
  - note: Host ends arguments phase; triggers AI cleanup in background.
- `POST /api/{session_id}/host/debate/end-round`
  - request: `none`
  - response: `200: any`
  - note: End Round
  - note: Host ends the current round early.
- `POST /api/{session_id}/host/debate/first-side`
  - request: `application/json: {side: string}`
  - response: `200: any`
  - note: Set First Side
  - note: Host picks which side speaks first in live debate.
- `POST /api/{session_id}/host/debate/force-assign`
  - request: `none`
  - response: `200: any`
  - note: Force Assign
  - note: Host force-assigns all unassigned participants.
- `POST /api/{session_id}/host/debate/phase`
  - request: `application/json: {phase: string}`
  - response: `200: any`
  - note: Advance Phase
  - note: Host advances the debate to a specific phase.
- `POST /api/{session_id}/host/debate/reset`
  - request: `none`
  - response: `200: any`
  - note: Reset Debate
  - note: Host resets all debate state.
- `POST /api/{session_id}/host/debate/round-timer`
  - request: `application/json: {round_index: int, seconds: int}`
  - response: `200: any`
  - note: Start Round Timer
  - note: Host starts a timed round.

### Host WS
- (none)

## Feature: Scores & Leaderboard

### Participant REST
- (none)

### Participant WS
- `scores_updated`
  - payload: `{type: 'scores_updated'  # enum: 'scores_updated', scores: dict[str, int]  # uuid → score (all participants)}`
  - note: One or more participants' scores changed
- `leaderboard_revealed`
  - payload: `{type: 'leaderboard_revealed'  # enum: 'leaderboard_revealed', positions: list[LeaderboardPosition]}`
  - note: Leaderboard overlay shown with top positions

### Host REST
- `POST /api/{session_id}/host/leaderboard/hide`
  - request: `none`
  - response: `200: any`
  - note: Hide Leaderboard
- `POST /api/{session_id}/host/leaderboard/show`
  - request: `none`
  - response: `200: any`
  - note: Show Leaderboard
- `DELETE /api/{session_id}/host/scores`
  - request: `none`
  - response: `200: any`
  - note: Reset Scores

### Host WS
- `leaderboard_revealed`
  - payload: `{type: 'leaderboard_revealed'  # enum: 'leaderboard_revealed', positions: list[LeaderboardPosition]}`
  - note: Leaderboard revealed (same payload as participant)

## Feature: Emoji Reactions

### Participant REST
- `POST /api/participant/emoji/reaction`
  - request: `application/json: {emoji: string}`
  - response: `200: any`
  - note: Emoji Reaction
  - note: Participant sends an emoji reaction.

### Participant WS
- (none)

### Host REST
- (none)

### Host WS
- `emoji_reaction`
  - payload: `{type: 'emoji_reaction'  # enum: 'emoji_reaction', emoji: string}`
  - note: Participant sent an emoji reaction — floating animation on host screen

## Feature: Quiz Generation

### Participant REST
- (none)

### Participant WS
- `quiz_status`
  - payload: `{type: 'quiz_status'  # enum: 'quiz_status', status: string  # "generating"|"ready"|"error", message: string}`
  - note: Quiz generation progress update
- `quiz_preview`
  - payload: `{type: 'quiz_preview'  # enum: 'quiz_preview', quiz?: any | null  # Set to null to clear the preview, question?: string, options?: list[string], multi?: bool, correct_indices?: list[int]}`
  - note: Quiz preview for host review before publishing (quiz=null to clear)

### Host REST
- `DELETE /api/{session_id}/host/quiz-preview`
  - request: `none`
  - response: `200: any`
  - note: Clear Quiz Preview
  - note: Host clears the current quiz preview.
- `POST /api/{session_id}/host/quiz-refine`
  - request: `application/json: {target: string, preview?: any | null}`
  - response: `200: any`
  - note: Request Quiz Refine
  - note: Host requests regeneration of a specific question or option.
- `POST /api/{session_id}/host/quiz-request`
  - request: `application/json: {minutes?: int | null, topic?: string | null}`
  - response: `200: any`
  - note: Request Quiz
  - note: Host requests a quiz — stores request for the orchestrator loop to pick up.
- `GET /api/{session_id}/quiz-md`
  - request: `none`
  - response: `200: any`
  - note: Get Quiz Md
  - note: Return the accumulated quiz markdown history.

### Host WS
- `quiz_status`
  - payload: `{type: 'quiz_status'  # enum: 'quiz_status', status: string  # "generating" | "ready" | "error", message?: string}`
  - note: Quiz generation progress update
- `quiz_preview`
  - payload: `{type: 'quiz_preview'  # enum: 'quiz_preview', quiz?: any | null  # Set to null to clear the preview, question?: string, options?: list[object], multi?: bool, correct_indices?: list[int]}`
  - note: Generated quiz ready for host review (quiz=null to clear)

## Feature: Paste & File Upload

### Participant REST
- `POST /api/participant/paste`
  - request: `application/json: {text: string}`
  - response: `200: any`
  - note: Paste Text
  - note: Participant pastes text to be seen by host.

### Participant WS
- (none)

### Host REST
- `GET /api/{session_id}/host/pastes`
  - request: `none`
  - response: `200: any`
  - note: Get Pastes
  - note: Return all pending paste entries grouped by participant uuid.
- `POST /api/{session_id}/host/uploads/seen`
  - request: `application/json: {uuid: string, file_id: string}`
  - response: `200: any`
  - note: Mark Uploaded File Seen
  - note: Mark an uploaded-file indicator as seen by host in daemon session state.

### Host WS
- `paste_received`
  - payload: `{type: 'paste_received'  # enum: 'paste_received', uuid: string  # Participant UUID who submitted the paste, id: string  # Paste ID, text: string}`
  - note: Participant submitted a text paste
- `file_uploaded`
  - payload: `{type: 'file_uploaded'  # enum: 'file_uploaded', uuid: string  # Participant UUID who uploaded the file, id: string  # File ID, filename: string, size: int  # File size in bytes, disk_path: string  # Absolute path on the host's disk where the file was saved by the daemon}`
  - note: Participant uploaded a file (daemon has downloaded it to session folder)

## Feature: Notes & Summary

### Participant REST
- `GET /api/participant/notes`
  - request: `none`
  - response: `200: any`
  - note: Get Notes
  - note: Get session notes content.
- `GET /api/participant/summary`
  - request: `none`
  - response: `200: any`
  - note: Get Summary
  - note: Get summary points and raw markdown.

### Participant WS
- `notes_updated`
  - payload: `{type: 'notes_updated'  # enum: 'notes_updated', count: int  # Number of non-empty lines in the notes file}`
  - note: Notes file changed — non-empty line count updated
- `summary_updated`
  - payload: `{type: 'summary_updated'  # enum: 'summary_updated', count: int  # Number of parsed bullet-point objects in ai-summary.md}`
  - note: AI summary file changed — parsed point count updated

### Host REST
- `GET /api/{session_id}/host/notes`
  - request: `none`
  - response: `200: any`
  - note: Get Host Notes
  - note: Return current session notes content.
- `GET /api/{session_id}/host/summary`
  - request: `none`
  - response: `200: any`
  - note: Get Host Summary
  - note: Return summary points, raw markdown, and updated_at timestamp.

### Host WS
- `notes_updated`
  - payload: `{type: 'notes_updated'  # enum: 'notes_updated', count: int  # Number of non-empty lines in the notes file}`
  - note: Notes file changed — non-empty line count updated
- `summary_updated`
  - payload: `{type: 'summary_updated'  # enum: 'summary_updated', count: int  # Number of parsed bullet-point objects in ai-summary.md}`
  - note: AI summary file changed — parsed point count updated

## Feature: Feedback

### Participant REST
- `POST /api/participant/misc/feedback`
  - request: `application/json: {text: string, participant_name?: string | null}`
  - response: `200: any`
  - note: Participant Feedback
  - note: Participant feedback submitted from floating feedback modal.

### Participant WS
- (none)

### Host REST
- (none)

### Host WS
- (none)

## Feature: Transcription

### Participant REST
- (none)

### Participant WS
- `transcription_language_pending`
  - payload: `{type: 'transcription_language_pending'  # enum: 'transcription_language_pending', language: string}`
  - note: Daemon detected a transcription language change

### Host REST
- `POST /api/transcription-language`
  - request: `application/json: {language: string}`
  - response: `200: any`
  - note: Set Transcription Language
  - note: Host sets the transcription language — stores pending request for daemon/macos-addons.
  - note: Accepted values: ro, en, auto.
- `GET /api/transcription-language/request`
  - request: `none`
  - response: `200: any`
  - note: Poll Transcription Language Request
  - note: Daemon/macos-addons polls for a pending language change request (clears on read).
  - note: Consumes and clears the pending transcription language request.

### Host WS
- (none)

## Feature: Cross-cutting: Reload

### Participant REST
- (none)

### Participant WS
- `reload`
  - payload: `{type: 'reload'  # enum: 'reload'}`
  - note: Daemon synced static files — browser should reload
  - note: Client should trigger full page reload to pick up new static assets.

### Host REST
- (none)

### Host WS
- `reload`
  - payload: `{type: 'reload'  # enum: 'reload'}`
  - note: Daemon synced static files — browser should reload
  - note: Host client should trigger full page reload to pick up new static assets.
