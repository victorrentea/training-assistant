# API Reference (Generated from Contracts)

Generated from `docs/openapi.yaml`, `docs/participant-ws.yaml`, and `docs/host-ws.yaml`.

## Table of Contents
- [Session](#feature-session)
- [Identity](#feature-identity)
- [Slides](#feature-slides)
- [Activity](#feature-activity)
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
- [Cross-cutting: Reload](#feature-cross-cutting-reload)

## Feature: Session

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Daemon Status<br>`GET /api/daemon-status` | - | `code_timestamp?: string` |
| Get Log Level<br>`GET /api/log-level` | - | `level: 'info' \| 'debug'` |
| Set Log Level<br>`POST /api/log-level` | `level: 'info' \| 'debug'` | - |
| Get Session Active, public endpoint: returns the active session_id or<br>null.<br>`GET /api/session/active` | - | `session_id?: string` |
| Host starts a new session (creates folder, assigns session_id, clean<br>slate).<br>`POST /api/session/create` | `name: string`<br>`type: 'workshop' \| 'conference'` | `session_name: string`<br>`session_id: string` |
| Host ends the current session. Railway closes WS connections on session<br>end.<br>`POST /api/session/end` | - | - |
| Host ends the current session. Railway closes WS connections on session<br>end.<br>`POST /api/session/end_talk` | - | - |
| List Session Folders<br>`GET /api/session/folders` | - | `folders: list[string]` |
| Host resumes an existing session folder. Uses session-state.json as<br>persisted storage.<br>`POST /api/session/resume` | `folder: string` | `session_name: string`<br>`session_id: string` |
| Host starts a nested talk (conference mode).<br>`POST /api/session/start_talk` | - | - |

## Feature: Identity

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Set Location, store participant city/timezone.<br>`POST /api/participant/location` | `location: string` | - |
| Rename Participant, returns 400 if not yet registered.<br>`PUT /api/participant/name` | `name: string` | - |
| Register Participant, idempotent for returning participants.<br>`POST /api/participant/register` | - | `name: string`<br>`avatar: string` |
| Roll Avatar Endpoint, re-roll avatar (conference mode only).<br>`POST /api/participant/roll-avatar` | `rejected?: list[string]` | `avatar: string` |
| Get Participant State, return full personalised state for a participant<br>— used on page load and WS reconnect;<br>returns participant-personalized full state snapshot.<br>`GET /api/participant/state` | - | `type?: string`<br>`mode: string`<br>`my_score: int`<br>`my_name: string`<br>`my_avatar: string`<br>`current_activity: string`<br>`participant_count: int`<br>`host_connected: bool`<br>`daemon_connected: bool`<br>`wordcloud_words: dict[str, int]`<br>`wordcloud_word_order: list[string]`<br>`wordcloud_topic: string`<br>`qa_questions: list[QAQuestionRaw {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`author_uuid:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`upvoter_uuids:list[string]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`answered:bool`<br>&nbsp;&nbsp;&nbsp;&nbsp;`timestamp:number`<br>`}]`<br>`poll?: PollData {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`question:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`options:list[PollOption {`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`}]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`multi:bool`<br>&nbsp;&nbsp;&nbsp;&nbsp;`correct_count?:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`source?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`page?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`timer_seconds?:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`timer_started_at?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`correct_ids?:list[string]`<br>`}`<br>`poll_active: bool`<br>`vote_counts: dict[str, int]`<br>`my_vote?: string \| list[string]`<br>`my_voted_ids?: list[string]`<br>`codereview: CodeReviewParticipantState {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`snippet?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`language?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`phase?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`confirmed_lines?:list[int]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`my_selections?:list[int]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`line_percentages?:dict[str, int]`<br>`}`<br>`debate_statement?: string`<br>`debate_phase?: string`<br>`debate_my_side?: string`<br>`debate_my_is_champion: bool`<br>`debate_side_counts: dict[str, int]`<br>`debate_arguments: list[DebateArgumentParticipant {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`author_uuid:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`side:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`upvoters:list[string]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`ai_generated:bool`<br>&nbsp;&nbsp;&nbsp;&nbsp;`merged_into?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`is_own:bool`<br>&nbsp;&nbsp;&nbsp;&nbsp;`has_upvoted:bool`<br>`}]`<br>`debate_champions: dict[str, string]`<br>`debate_auto_assigned: list[string]`<br>`debate_first_side?: string`<br>`debate_round_index?: int`<br>`debate_round_timer_seconds?: int`<br>`debate_round_timer_started_at?: string`<br>`slides_current?: SlidesCurrentPayload {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`slug?:string`<br>`}`<br>`session_main?: SessionMainPayload {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`mode?:string`<br>`}`<br>`session_name?: string`<br>`leaderboard_data?: LeaderboardData {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`entries:list[LeaderboardEntry {`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`uuid:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`name:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`score:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`}]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`total_participants:int`<br>`}`<br>`summary_count: int`<br>`notes_count: int` |

### Participant WS
| Message | Payload |
| --- | --- |
| `participant_count_updated` | `count: int` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Host State, return full state for host page load<br>— replicates Railway build_for_host();<br>returns host-facing full state snapshot.<br>`GET /api/{session_id}/host/state` | - | `type?: string`<br>`mode: string`<br>`current_activity: string`<br>`participant_count: int`<br>`participants: list[HostParticipant {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`uuid:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`name:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`score:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`location:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`avatar:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`paste_texts?:list[PasteEntry {`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`}]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`received_files?:list[UploadedFileEntry {`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`filename:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`size:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`disk_path:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`seen_by_host:bool`<br>&nbsp;&nbsp;&nbsp;&nbsp;`}]`<br>`}]`<br>`daemon_connected: bool`<br>`overlay_connected: bool`<br>`wordcloud_words: dict[str, int]`<br>`wordcloud_word_order: list[string]`<br>`wordcloud_topic: string`<br>`qa_questions: list[HostQAQuestion {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`author:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`author_uuid:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`author_avatar:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`upvote_count:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`upvoters:list[string]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`answered:bool`<br>&nbsp;&nbsp;&nbsp;&nbsp;`timestamp:number`<br>`}]`<br>`poll?: PollData {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`question:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`options:list[PollOption {`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`}]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`multi:bool`<br>&nbsp;&nbsp;&nbsp;&nbsp;`correct_count?:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`source?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`page?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`timer_seconds?:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`timer_started_at?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`correct_ids?:list[string]`<br>`}`<br>`poll_active: bool`<br>`vote_counts: dict[str, int]`<br>`votes: dict[str, HostPollVote {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`option_ids:list[string]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`voted_at:string`<br>`}]`<br>`codereview: HostCodeReviewState {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`snippet?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`language?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`phase?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`confirmed_lines?:list[int]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`selections?:dict[str, list[int]]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`line_percentages?:dict[str, int]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`line_counts?:dict[str, int]`<br>`}`<br>`debate_statement?: string`<br>`debate_phase?: string`<br>`debate_side_counts: dict[str, int]`<br>`debate_sides: dict[str, string]`<br>`debate_arguments: list[DebateArgumentHost {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`author_uuid:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`side:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`upvoters:list[string]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`ai_generated:bool`<br>&nbsp;&nbsp;&nbsp;&nbsp;`merged_into?:string`<br>`}]`<br>`debate_champions: dict[str, string]`<br>`debate_auto_assigned: list[string]`<br>`debate_first_side?: string`<br>`debate_round_index?: int`<br>`debate_round_timer_seconds?: int`<br>`debate_round_timer_started_at?: string`<br>`slides_current?: SlidesCurrentPayload {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`slug?:string`<br>`}`<br>`slides_log: list[SlidesLogEntry {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`file:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`slide:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`seconds_spent:number`<br>&nbsp;&nbsp;&nbsp;&nbsp;`timestamp:string`<br>`}]`<br>`slides_log_deep_count: int`<br>`slides_log_topic?: string`<br>`session_main?: SessionMainPayload {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`mode?:string`<br>`}`<br>`session_name?: string`<br>`session_id?: string`<br>`join_base_url: string`<br>`daemon_session_folder?: string`<br>`daemon_session_notes?: string`<br>`leaderboard_data?: LeaderboardData {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`entries:list[LeaderboardEntry {`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`uuid:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`name:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`score:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`}]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`total_participants:int`<br>`}`<br>`summary_count: int`<br>`summary_updated_at?: string`<br>`notes_count: int`<br>`token_usage: TokenUsage {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`input_tokens:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`output_tokens:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`estimated_cost_usd:number`<br>`}`<br>`transcript_line_count: int`<br>`transcript_total_lines: int`<br>`transcript_latest_ts?: string`<br>`quiz_preview?: QuizPreviewPayload-Output {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`question?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`options?:list[string]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`multi?:bool`<br>&nbsp;&nbsp;&nbsp;&nbsp;`correct_indices?:list[int]`<br>`}` |

### Host WS
| Message | Payload |
| --- | --- |
| Participant list changed (join/register/rename/location) — sent by daemon directly<br>`participant_list_updated` | `participants: list[HostParticipant {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`uuid:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`name:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`score:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`location?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`avatar:string`<br>`}]` |

## Feature: Slides

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Slides Cache Status, primarily for diagnostics;<br>UI cache invalidation is event-driven via slides_cache_status WS.<br>`GET /api/participant/slides-cache-status` | - | `slides_cache_status?: dict[str, SlidesCacheStatusEntry {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`status:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`size_bytes?:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`downloaded_at?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`modified_at?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`title?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`name?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`error?:string`<br>`}]` |

### Participant WS
| Message | Payload |
| --- | --- |
| Host navigated to a new slide<br>`slides_current` | `slides_current?: SlidesCurrent {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`url?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`slug?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`presentation_name?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`current_page?:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`updated_at?:string`<br>`}  # null means no active slide` |
| Invalidation signal — participant must call GET /api/slides to refresh<br>Client must refetch slide list; payload intentionally carries no cache map.<br>`slides_cache_status` | - |

### Host WS
| Message | Payload |
| --- | --- |
| Invalidation signal — host must call GET /api/slides to refresh<br>Host should refetch slides list; payload intentionally carries no cache map.<br>`slides_cache_status` | - |

## Feature: Activity

### Participant WS
| Message | Payload |
| --- | --- |
| `activity_updated` | `current_activity: 'none' \| 'poll' \| 'wordcloud' \| 'qa' \| 'codereview' \| 'debate'` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Host sets the current activity.<br>`POST /api/{session_id}/host/activity` | `activity: string` | `ok?: bool`<br>`current_activity: string` |
| Host sets the current activity.<br>`PUT /api/{session_id}/host/activity` | `activity: string` | `ok?: bool`<br>`current_activity: string` |

## Feature: Poll

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Participant casts a vote. Votes are final once submitted;<br>re-vote is rejected.<br>`POST /api/participant/poll/vote` | `option_ids: list[string]` | - |

### Participant WS
| Message | Payload |
| --- | --- |
| Poll opened for voting<br>Participants can vote only while poll is open.<br>`poll_opened` | `poll: Poll {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`question:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`options:list[object]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`multi:bool`<br>`}` |
| Voting closed by host<br>`poll_closed` | `vote_counts: dict[str, int]  # option_id → vote count`<br>`total_votes: int` |
| Host revealed correct answers<br>`poll_correct_revealed` | `correct_ids: list[string]` |
| Poll removed by host<br>`poll_cleared` | - |
| Host started a countdown timer for the poll<br>`poll_timer_started` | `seconds: int` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Host deletes the current poll.<br>`DELETE /api/{session_id}/host/poll` | - | - |
| Host creates a new poll.<br>`POST /api/{session_id}/host/poll` | `question?: string`<br>`options?: list[PollOptionRequest {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>`}]`<br>`multi?: bool`<br>`correct_count?: int` | `ok?: bool`<br>`poll: PollResponse {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`question:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`options:list[PollOptionRequest {`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`}]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`multi:bool`<br>&nbsp;&nbsp;&nbsp;&nbsp;`correct_count?:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`source?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`page?:string`<br>`}` |
| Host closes the poll.<br>`POST /api/{session_id}/host/poll/close` | - | `ok?: bool`<br>`vote_counts: dict[str, int]`<br>`total_votes: int` |
| Host reveals correct answers and awards scores.<br>`PUT /api/{session_id}/host/poll/correct` | `correct_ids?: list[string]` | - |
| Host opens the poll for voting.<br>`POST /api/{session_id}/host/poll/open` | - | - |
| Set Poll Status, compatibility: {open: true} → open_poll, {open: false}<br>→ close_poll.<br>`PUT /api/{session_id}/host/poll/status` | `open: bool` | `OkResponse {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`ok?:bool`<br>`} \| ClosePollResponse {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`ok?:bool`<br>&nbsp;&nbsp;&nbsp;&nbsp;`vote_counts:dict[str, int]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`total_votes:int`<br>`}` |
| Host starts a countdown timer for the poll.<br>`POST /api/{session_id}/host/poll/timer` | `seconds?: int` | - |

### Host WS
| Message | Payload |
| --- | --- |
| Host-only notification when a new poll is created (before opening)<br>`poll_ai_generated` | `poll: dict  # Poll data {id, question, options[], multi}` |
| Real-time vote tally while poll is open<br>Host-only event; participants do not receive live vote tallies.<br>`vote_update` | `votes: dict[str, int]  # option_id → vote count` |

## Feature: Word Cloud

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Participant submits a word to the word cloud.<br>`POST /api/participant/wordcloud/word` | `word: string` | - |

### Participant WS
| Message | Payload |
| --- | --- |
| Word cloud state changed (new word or topic update)<br>`wordcloud_updated` | `words: dict[str, int]  # word → count`<br>`word_order: list[string]  # Newest-first insertion order`<br>`topic: string` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Host clears the word cloud.<br>`POST /api/{session_id}/host/wordcloud/clear` | - | - |
| Host sets the word cloud topic.<br>`POST /api/{session_id}/host/wordcloud/topic` | `topic: string` | - |
| Host submits a word — same as participant but no scoring.<br>`POST /api/{session_id}/host/wordcloud/word` | `word: string` | - |

### Host WS
| Message | Payload |
| --- | --- |
| Word cloud updated (same payload as participant)<br>`wordcloud_updated` | `words: dict[str, int]  # word → count`<br>`word_order: list[string]  # Words ordered newest first`<br>`topic: string` |

## Feature: Q&A

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Participant submits a Q&A question.<br>`POST /api/participant/qa/submit` | `text: string` | - |
| Participant upvotes a Q&A question.<br>`POST /api/participant/qa/upvote` | `question_id: string` | - |

### Participant WS
| Message | Payload |
| --- | --- |
| Q&A list changed (new question, upvote, edit, delete)<br>`qa_updated` | `questions: list[QAQuestion {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`author_uuid:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`upvoter_uuids:list[string]  # Client computes is_own and has_upvoted locally from its own UUID`<br>&nbsp;&nbsp;&nbsp;&nbsp;`answered:bool`<br>&nbsp;&nbsp;&nbsp;&nbsp;`timestamp:number`<br>`}]` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Host clears all Q&A questions.<br>`POST /api/{session_id}/host/qa/clear` | - | - |
| Host deletes a question.<br>`DELETE /api/{session_id}/host/qa/question/{question_id}` | - | - |
| Host toggles a question's answered flag.<br>`PUT /api/{session_id}/host/qa/question/{question_id}/answered` | `answered?: bool` | - |
| Host edits a question's text.<br>`PUT /api/{session_id}/host/qa/question/{question_id}/text` | `text: string` | - |
| Host submits a Q&A question — no scoring.<br>`POST /api/{session_id}/host/qa/submit` | `text: string` | - |

### Host WS
| Message | Payload |
| --- | --- |
| Q&A list changed (same structure as participant)<br>`qa_updated` | `questions: list[QAQuestion {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`author_uuid:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`upvoter_uuids:list[string]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`answered:bool`<br>&nbsp;&nbsp;&nbsp;&nbsp;`timestamp:number`<br>`}]` |

## Feature: Code Review

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Update Selection, participant sets their selected lines (full<br>replacement).<br>`PUT /api/participant/codereview/selection` | `lines?: list[int]` | - |

### Participant WS
| Message | Payload |
| --- | --- |
| Host opened a code snippet for review<br>`codereview_opened` | `snippet: string`<br>`language?: string` |
| Host closed the line selection phase<br>`codereview_selection_closed` | - |
| Host confirmed a line as problematic<br>`codereview_line_confirmed` | `line: int` |
| Code review removed by host<br>`codereview_cleared` | - |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Host clears the code review.<br>`DELETE /api/{session_id}/host/codereview` | - | - |
| Host creates a code review session.<br>`POST /api/{session_id}/host/codereview` | `snippet: string`<br>`language?: string`<br>`smart_paste?: bool` | - |
| Host confirms a line as problematic and awards points.<br>`PUT /api/{session_id}/host/codereview/confirm-line` | `line: int` | `ok?: bool`<br>`confirmed_line: int` |
| Set Codereview Status, host closes the selection phase.<br>`PUT /api/{session_id}/host/codereview/status` | `open?: bool` | `ok?: bool`<br>`phase: string` |

### Host WS
| Message | Payload |
| --- | --- |
| Aggregated line selection counts (host-only)<br>`codereview_selections_updated` | `line_counts: dict[str, int]  # line number → count of participants who selected it` |

## Feature: Debate

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Participant submits a debate argument.<br>`POST /api/participant/debate/argument` | `text: string` | - |
| Participant picks a side (for/against).<br>`POST /api/participant/debate/pick-side` | `side: string` | - |
| Participant upvotes a debate argument.<br>`POST /api/participant/debate/upvote` | `argument_id: string` | - |
| Participant volunteers as champion for their side.<br>`POST /api/participant/debate/volunteer` | - | - |

### Participant WS
| Message | Payload |
| --- | --- |
| Full debate state snapshot<br>`debate_updated` | `statement?: string`<br>`phase?: 'side_selection' \| 'arguments' \| 'ai_cleanup' \| 'prep' \| 'live_debate' \| 'ended'`<br>`sides?: dict[str, string]  # uuid → "for"\|"against"`<br>`arguments?: list[DebateArgument {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`author_uuid:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`side:'for' \| 'against'`<br>&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`upvoters:list[string]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`ai_generated:bool`<br>&nbsp;&nbsp;&nbsp;&nbsp;`merged_into?:string`<br>`}]`<br>`champions?: dict[str, string]  # "for"\|"against" → uuid`<br>`auto_assigned?: list[string]`<br>`first_side?: string`<br>`round_index?: int`<br>`round_timer_seconds?: int`<br>`round_timer_started_at?: string` |
| A timed debate round started<br>`debate_timer` | `round_index: int`<br>`seconds: int`<br>`started_at: string` |
| `debate_round_ended` | - |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Host launches a debate with a statement.<br>`POST /api/{session_id}/host/debate` | `statement: string` | - |
| Receive Ai Result, manual/skip AI result<br>— host posts AI cleanup results directly.<br>`POST /api/{session_id}/host/debate/ai-result` | `merges?: list[DebateAiMerge {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`keep_id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`remove_ids?:list[string]`<br>`}]`<br>`cleaned?: list[DebateAiCleaned {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>`}]`<br>`new_arguments?: list[DebateAiNewArgument {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`side:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>`}]` | - |
| Host closes side selection; auto-assigns remaining participants.<br>`POST /api/{session_id}/host/debate/close-selection` | - | - |
| Host ends arguments phase; triggers AI cleanup in background.<br>`POST /api/{session_id}/host/debate/end-arguments` | - | - |
| Host ends the current round early.<br>`POST /api/{session_id}/host/debate/end-round` | - | - |
| Set First Side, host picks which side speaks first in live debate.<br>`POST /api/{session_id}/host/debate/first-side` | `side: string` | - |
| Force Assign, host force-assigns all unassigned participants.<br>`POST /api/{session_id}/host/debate/force-assign` | - | - |
| Host advances the debate to a specific phase.<br>`POST /api/{session_id}/host/debate/phase` | `phase: string` | `ok?: bool`<br>`phase: string` |
| Host resets all debate state.<br>`POST /api/{session_id}/host/debate/reset` | - | - |
| Host starts a timed round.<br>`POST /api/{session_id}/host/debate/round-timer` | `round_index: int`<br>`seconds: int` | - |

## Feature: Scores & Leaderboard

### Participant WS
| Message | Payload |
| --- | --- |
| One or more participants' scores changed<br>`scores_updated` | `scores: dict[str, int]  # uuid → score (all participants)` |
| Leaderboard overlay shown with top positions<br>`leaderboard_revealed` | `positions: list[LeaderboardPosition {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`rank:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`name:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`score:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`avatar:string`<br>`}]` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Hide Leaderboard<br>`POST /api/{session_id}/host/leaderboard/hide` | - | - |
| Show Leaderboard<br>`POST /api/{session_id}/host/leaderboard/show` | - | - |
| Reset Scores<br>`DELETE /api/{session_id}/host/scores` | - | - |

### Host WS
| Message | Payload |
| --- | --- |
| Leaderboard revealed (same payload as participant)<br>`leaderboard_revealed` | `positions: list[LeaderboardPosition {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`rank:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`name:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`score:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`avatar:string`<br>`}]` |

## Feature: Emoji Reactions

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Emoji Reaction, participant sends an emoji reaction.<br>`POST /api/participant/emoji/reaction` | `emoji: string` | - |

### Host WS
| Message | Payload |
| --- | --- |
| Participant sent an emoji reaction — floating animation on host screen<br>`emoji_reaction` | `emoji: string` |

## Feature: Quiz Generation

### Participant WS
| Message | Payload |
| --- | --- |
| Quiz generation progress update<br>`quiz_status` | `status: string  # "generating"\|"ready"\|"error"`<br>`message: string` |
| Quiz preview for host review before publishing (quiz=null to clear)<br>`quiz_preview` | `quiz?: any  # Set to null to clear the preview`<br>`question?: string`<br>`options?: list[string]`<br>`multi?: bool`<br>`correct_indices?: list[int]` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Host clears the current quiz preview.<br>`DELETE /api/{session_id}/host/quiz-preview` | - | - |
| Host requests regeneration of a specific question or option.<br>`POST /api/{session_id}/host/quiz-refine` | `target: string`<br>`preview?: QuizPreviewPayload-Input {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`quiz?:dict[str, any]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`question?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`options?:list[string]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`multi?:bool`<br>&nbsp;&nbsp;&nbsp;&nbsp;`correct_indices?:list[int]`<br>`}` | - |
| Host requests a quiz<br>— stores request for the orchestrator loop to pick up.<br>`POST /api/{session_id}/host/quiz-request` | `minutes?: int`<br>`topic?: string` | - |
| Get Quiz Md, return the accumulated quiz markdown history.<br>`GET /api/{session_id}/quiz-md` | - | `content: string` |

### Host WS
| Message | Payload |
| --- | --- |
| Quiz generation progress update<br>`quiz_status` | `status: string  # "generating" \| "ready" \| "error"`<br>`message?: string` |
| Generated quiz ready for host review (quiz=null to clear)<br>`quiz_preview` | `quiz?: any  # Set to null to clear the preview`<br>`question?: string`<br>`options?: list[object]`<br>`multi?: bool`<br>`correct_indices?: list[int]` |

## Feature: Paste & File Upload

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Participant pastes text to be seen by host.<br>`POST /api/participant/paste` | `text: string` | - |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Pastes, return all pending paste entries grouped by participant<br>uuid.<br>`GET /api/{session_id}/host/pastes` | - | `pastes?: dict[str, list[PasteEntry {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>`}]]` |
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
| Get Notes<br>`GET /api/participant/notes` | - | `notes_content?: string` |
| Get Summary<br>`GET /api/participant/summary` | - | `points?: list[SummaryPoint {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`source:string`<br>`}]`<br>`raw_markdown?: string`<br>`updated_at?: string` |

### Participant WS
| Message | Payload |
| --- | --- |
| Notes file changed — non-empty line count updated<br>`notes_updated` | `count: int  # Number of non-empty lines in the notes file` |
| AI summary file changed — parsed point count updated<br>`summary_updated` | `count: int  # Number of parsed bullet-point objects in ai-summary.md` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Host Notes, return current session notes content.<br>`GET /api/{session_id}/host/notes` | - | `notes_content?: string` |
| Get Host Summary, return summary points, raw markdown, and updated_at<br>timestamp.<br>`GET /api/{session_id}/host/summary` | - | `points?: list[SummaryPoint {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`source:string`<br>`}]`<br>`raw_markdown?: string`<br>`updated_at?: string` |

### Host WS
| Message | Payload |
| --- | --- |
| Notes file changed — non-empty line count updated<br>`notes_updated` | `count: int  # Number of non-empty lines in the notes file` |
| AI summary file changed — parsed point count updated<br>`summary_updated` | `count: int  # Number of parsed bullet-point objects in ai-summary.md` |

## Feature: Feedback

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Participant Feedback<br>`POST /api/participant/misc/feedback` | `text: string`<br>`participant_name?: string` | - |

## Feature: Cross-cutting: Reload

### Participant WS
| Message | Payload |
| --- | --- |
| Daemon synced static files — browser should reload<br>Client should trigger full page reload to pick up new static assets.<br>`reload` | - |

### Host WS
| Message | Payload |
| --- | --- |
| Daemon synced static files — browser should reload<br>Host client should trigger full page reload to pick up new static assets.<br>`reload` | - |
