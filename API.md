# API Reference (Generated from Contracts)

Generated from `docs/openapi.yaml`, `docs/participant-ws.yaml`, `docs/host-ws.yaml`, `docs/railway-openapi.yaml`, `docs/railway-ws.yaml`, `docs/addons-ws.yaml`.

## Table of Contents
- [Session](#feature-session)
- [Identity](#feature-identity)
- [Participant State](#feature-participant-state)
- [Host State](#feature-host-state)
- [Slides](#feature-slides)
- [Activity](#feature-activity)
- [Poll](#feature-poll)
- [Word Cloud](#feature-word-cloud)
- [Q&A](#feature-qa)
- [Code Review](#feature-code-review)
- [Debate](#feature-debate)
- [Scores & Leaderboard](#feature-scores--leaderboard)
- [Emoji Reactions](#feature-emoji-reactions)
- [Paste & File Upload](#feature-paste--file-upload)
- [Notes, Summary & Agenda](#feature-notes,-summary--agenda)
- [Feedback](#feature-feedback)
- [Cross-cutting: Reload](#feature-cross-cutting-reload)
- [Infrastructure](#feature-infrastructure)
- [Intellij](#feature-intellij)

## Feature: Session

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Daemon Status<br>`GET /api/daemon-status` | - | `code_timestamp?: string` |
| Get Log Level<br>`GET /api/log-level` | - | `level: 'info' \| 'debug'` |
| Set Log Level<br>`POST /api/log-level` | `level: 'info' \| 'debug'` | - |
| Get Session Active, public endpoint: returns the active session_id or null.<br>`GET /api/session/active` | - | `session_id?: string` |
| Host starts a new session (creates folder, assigns session_id, clean slate).<br>`POST /api/session/create` | `name: string`<br>`type: 'workshop' \| 'talk'` | `session_name: string`<br>`session_id: string` |
| Host ends the current session. Railway closes WS connections on session end.<br>`POST /api/session/end` | - | - |
| List Session Folders<br>`GET /api/session/folders` | - | `folders: list[FolderInfo{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`name:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`session_type?:string`<br>`}]` |
| Host resumes an existing session folder. Uses session-state.json as persisted storage.<br>`POST /api/session/resume` | `folder: string` | `session_name: string`<br>`session_id: string` |
| Talk Presentation Path, host drops a PPTX file during a talk — resolve GDrive URL, trigger Railway download, push current_slide_updated.<br>`POST /api/session/talk-presentation-path` | `path: string` | - |

### Railway REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Active Session ID, daemon calls on startup to discover if a session is already active on Railway; returns the current session_id or null if no session is active.<br>`GET /api/session/active` | - | `session_id: any  # Current active session ID, or null if no session is active.` |

### Railway WS
| Message | Payload |
| --- | --- |
| Daemon announces current active session to Railway on connect or session change<br>`set_session_id` | `session_id?: string` |

### Addons WS
| Message | Payload |
| --- | --- |
| Notify addons that a workshop session has started<br>`session_started` | `participant_url: string  # Full URL for participants to join the session` |
| Notify addons that the workshop session has ended<br>`session_ended` | - |

## Feature: Identity

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Set Location, store participant city/timezone.<br>`PUT /api/participant/location` | `location: string` | - |
| Rename Participant, returns 400 if not yet registered.<br>`PUT /api/participant/name` | `name: string` | - |
| Register Participant, idempotent for returning participants.<br>`POST /api/participant/register` | `name?: string`<br>`location?: string` | `name: string`<br>`avatar: string` |
| Rejoin Participant, lookup-only identity restore for returning UUIDs in current session.<br>`POST /api/participant/rejoin` | - | `name: string`<br>`avatar: string` |
| Roll Avatar Endpoint, re-roll avatar (conference mode only).<br>`POST /api/participant/roll-avatar` | `rejected?: list[string]` | `avatar: string` |

### Participant WS
| Message | Payload |
| --- | --- |
| Participant total count changed<br>'count' includes all known non-host participants in the active session.<br>`active_participants_count_updated` | `count: int` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Resolve Participant Locations, backfill city name + timezone + country for all participants missing geo metadata.<br>`POST /api/{session_id}/host/participants/resolve-locations` | - | - |

### Host WS
| Message | Payload |
| --- | --- |
| Participant list changed (join/register/rename/location) — sent by daemon directly<br>`participant_list_updated` | `participants: list[HostParticipant{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`uuid:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`name:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`score:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`location?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`avatar:string`<br>`}]` |

### Railway WS
| Message | Payload |
| --- | --- |
| Participant connected or disconnected from Railway<br>`participant_presence` | `uuid: string  # Participant UUID`<br>`online: bool` |
| Railway pushes current online participant list to newly connected daemon<br>`daemon_state_push` | `online_participants: list[string]  # UUIDs of currently online participants` |

## Feature: Participant State

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Participant State, return full personalised state for a participant — used on page load and WS reconnect; returns participant-personalized full state snapshot.<br>`GET /api/participant/state` | - | `mode: string`<br>`my_score: int`<br>`my_name: string`<br>`my_avatar: string`<br>`current_activity: string`<br>`session_name?: string`<br>`wordcloud: WordcloudData{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`words:dict[str, int]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`word_order:list[string]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`topic:string`<br>`}`<br>`qa_questions: list[QAQuestionRaw{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`author_uuid:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`upvoter_uuids:list[string]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`answered:bool`<br>&nbsp;&nbsp;&nbsp;&nbsp;`timestamp:number`<br>`}]`<br>`poll?: PollData{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`question:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`options:list[string]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`multi:bool`<br>&nbsp;&nbsp;&nbsp;&nbsp;`correct_count?:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`end_timer_seconds?:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`end_timer_started_at?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`correct_indices?:list[int]`<br>`}`<br>`poll_active: bool`<br>`vote_counts: list[int]`<br>`my_voted_indices?: list[int]`<br>`poll_correct_indices?: list[int]`<br>`codereview: CodeReviewParticipantState{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`snippet?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`language?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`phase?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`confirmed_lines?:list[int]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`my_selections?:list[int]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`line_percentages?:dict[str, int]`<br>`}`<br>`debate: DebateData{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`statement?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`phase?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`my_side?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`my_is_champion:bool`<br>&nbsp;&nbsp;&nbsp;&nbsp;`side_counts:dict[str, int]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`arguments:list[DebateArgumentParticipant{`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`author_uuid:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`side:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`upvoters:list[string]`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`ai_generated:bool`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`merged_into?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`is_own:bool`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`has_upvoted:bool`<br>&nbsp;&nbsp;&nbsp;&nbsp;`}]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`champions:dict[str, string]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`auto_assigned:list[string]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`first_side?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`round_index?:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`round_timer_seconds?:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`round_timer_started_at?:string`<br>`}`<br>`slides_current?: CurrentSlide{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`slug:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`page:int`<br>`}`<br>`talk_presentation_slug?: string`<br>`notes_updated_at?: string`<br>`summary_updated_at?: string`<br>`slides_history_count: int`<br>`gdrive_url?: string`<br>`has_agenda?: bool` |

## Feature: Host State

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Host State, return full state for host page load — replicates Railway build_for_host(); returns host-facing full state snapshot.<br>`GET /api/{session_id}/host/state` | - | `type?: string`<br>`mode: string`<br>`current_activity: string`<br>`participant_count: int`<br>`participants: list[HostParticipant{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`uuid:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`name:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`score:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`location:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`location_tz?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`location_country?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`avatar:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`paste_texts?:list[PasteEntry{`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`}]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`received_files?:list[UploadedFileEntry{`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`filename:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`size:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`disk_path:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`seen_by_host:bool`<br>&nbsp;&nbsp;&nbsp;&nbsp;`}]`<br>`}]`<br>`daemon_connected: bool`<br>`railway_connected: bool`<br>`overlay_connected: bool`<br>`gdrive_running: bool`<br>`wordcloud_words: dict[str, int]`<br>`wordcloud_word_order: list[string]`<br>`wordcloud_topic: string`<br>`qa_questions: list[HostQAQuestion{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`author:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`author_uuid:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`author_avatar:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`upvote_count:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`upvoters:list[string]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`answered:bool`<br>&nbsp;&nbsp;&nbsp;&nbsp;`timestamp:number`<br>`}]`<br>`codereview: HostCodeReviewState{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`snippet?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`language?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`phase?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`confirmed_lines?:list[int]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`selections?:dict[str, list[int]]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`line_percentages?:dict[str, int]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`line_counts?:dict[str, int]`<br>`}`<br>`debate_statement?: string`<br>`debate_phase?: string`<br>`debate_side_counts: dict[str, int]`<br>`debate_sides: dict[str, string]`<br>`debate_arguments: list[DebateArgumentHost{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`author_uuid:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`side:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`upvoters:list[string]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`ai_generated:bool`<br>&nbsp;&nbsp;&nbsp;&nbsp;`merged_into?:string`<br>`}]`<br>`debate_champions: dict[str, string]`<br>`debate_auto_assigned: list[string]`<br>`debate_first_side?: string`<br>`debate_round_index?: int`<br>`debate_round_timer_seconds?: int`<br>`debate_round_timer_started_at?: string`<br>`talk_presentation_name?: string`<br>`talk_presentation_slug?: string`<br>`slides_log_deep_count: int`<br>`slides_log_topic?: string`<br>`git_repos?: list[GitRepoActivity{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`url:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`branch:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`files?:list[string]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`file_urls?:dict[str, string]`<br>`}]`<br>`git_repos_count?: int`<br>`session_id?: string`<br>`join_base_url: string`<br>`daemon_session_folder?: string`<br>`daemon_session_notes?: string`<br>`session_type?: string`<br>`notes_updated_at?: string`<br>`summary_updated_at?: string`<br>`transcript_line_count: int`<br>`transcript_total_lines: int`<br>`transcript_latest_ts?: string` |

## Feature: Slides

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Slides Decks, returns cache status snapshot for all known decks; called on initial page load and after decks_updated WS.<br>`GET /api/participant/slides/decks` | - | `decks?: dict[str, Deck{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`status:SlideCacheStatus: 'not_cached' \| 'cached' \| 'downloading' \| 'download_failed'`<br>&nbsp;&nbsp;&nbsp;&nbsp;`size_bytes?:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`downloaded_at?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`modified_at?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`title:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`error?:string`<br>`}]` |
| Get Slides History, return accumulated slide viewing history for the current session.<br>`GET /api/participant/slides/history` | - | `slides_log: list[SlidesLogEntry{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`slug:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`slide:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`seconds_spent:number`<br>`}]` |

### Participant WS
| Message | Payload |
| --- | --- |
| Host navigated to a new slide<br>`current_slide_updated` | `current_slide: CurrentSlide{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`slug:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`page:int`<br>`}` |
| Deck cache status changed — contains full cache map to avoid polling<br>'refreshed_slugs' lists slugs whose PDF content changed (hash changed) — trigger re-download if that slide is currently open.<br>`decks_updated` | `refreshed_slugs?: list[string]`<br>`decks?: dict[str, Deck{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`status:'not_cached' \| 'cached' \| 'downloading' \| 'download_failed'`<br>&nbsp;&nbsp;&nbsp;&nbsp;`size_bytes?:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`downloaded_at?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`modified_at?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`title:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`error?:string`<br>`}]` |
| Participant slide history count changed<br>`slides_history_updated` | `count: int` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Slides Compilation, compile all viewed slide pages into one PDF and return as a download; long-running: may trigger Railway to download PDFs from Google Drive first; progress is logged to the daemon log.<br>`GET /api/{session_id}/host/slides-compilation` | - | `any` |

### Host WS
| Message | Payload |
| --- | --- |
| Deck cache status changed — contains full cache map to avoid polling<br>'refreshed_slugs' lists slugs whose PDF content changed (hash changed) — trigger re-download if that slide is currently open.<br>`decks_updated` | `refreshed_slugs?: list[string]`<br>`decks?: dict[str, Deck{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`status:'not_cached' \| 'cached' \| 'downloading' \| 'download_failed'`<br>&nbsp;&nbsp;&nbsp;&nbsp;`size_bytes?:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`downloaded_at?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`modified_at?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`title:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`error?:string`<br>`}]` |
| PDF was successfully downloaded to Railway and is ready to serve<br>`talk_pdf_ready` | `slug: string` |
| PDF download from Google Drive failed — host should be notified<br>`talk_pdf_failed` | - |

### Railway REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Download Slide PDF from Google Drive, daemon asks Railway to fetch a PDF export from Google Drive and cache it locally on Railway; railway downloads the file, caches it, and returns the SHA-256 hash so the daemon can detect content changes.<br>`POST /api/slides/download-from-gdrive/{slug}` | `drive_export_url: string  # Google Drive PDF export URL for the slide deck.` | `status: string  # Always "cached" on success.`<br>`sha256: string  # SHA-256 hex digest of the cached PDF file.`<br>`size: int  # File size in bytes.` |

### Railway WS
| Message | Payload |
| --- | --- |
| Railway requests daemon to sync static files and PDF cache<br>`sync_files` | `static_hashes: dict[str, string]  # filename → hash of current Railway-served static file`<br>`pdf_slugs: dict[str, string]  # slug → drive_export_url for known PDF slides` |

### Addons WS
| Message | Payload |
| --- | --- |
| Current PowerPoint slide changed<br>`slide_presenting_now` | `deck: string  # PowerPoint file name`<br>`slide: int  # 1-based slide number`<br>`presenting: bool  # Whether slideshow mode is active` |
| Periodic delta of per-slide viewing durations (sent every 60s)<br>`slides_viewed` | `slides: list[SlideViewDelta{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`fileName:string  # PowerPoint file name`<br>&nbsp;&nbsp;&nbsp;&nbsp;`page:int  # 1-based slide number`<br>&nbsp;&nbsp;&nbsp;&nbsp;`seconds:int  # Seconds viewed since last report (delta)`<br>`}]  # Delta viewing durations since last send` |

## Feature: Activity

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Git Activity, return accumulated git file-open activity for the current session.<br>`GET /api/participant/git-activity` | - | `git_repos: list[GitRepoActivity{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`url:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`branch:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`files?:list[string]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`file_urls?:dict[str, string]`<br>`}]` |

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
| Participant casts a vote. Votes are final once submitted; re-vote is rejected.<br>`POST /api/participant/poll/vote` | `options: list[int]` | - |

### Participant WS
| Message | Payload |
| --- | --- |
| Poll opened for voting<br>Participants can vote only while poll is open.<br>`poll_opened` | `poll: Poll{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`question:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`options:list[string]  # Poll options as plain text strings`<br>&nbsp;&nbsp;&nbsp;&nbsp;`multi:bool`<br>`}` |
| Voting closed by host<br>Participants can see how others voted via vote_counts.<br>`poll_ended` | `vote_counts: list[int]  # Vote count per option, indexed by option position` |
| Host revealed correct answers<br>Participants use correct_indices (0-based) to highlight correct options in the UI.<br>`poll_correct_revealed` | `correct_indices: list[int]  # 0-based indices of correct options` |
| Poll removed by host<br>`poll_cleared` | - |
| Host started a countdown timer for the poll<br>`poll_end_countdown_started` | `seconds: int`<br>`started_at: string` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Host deletes the current poll.<br>`DELETE /api/{session_id}/host/poll` | - | - |
| Get Poll State, return full poll state for host poll tab.<br>`GET /api/{session_id}/host/poll` | - | `id?: string`<br>`question?: string`<br>`options?: list[string]`<br>`multi?: bool`<br>`correct_count?: int`<br>`end_timer_seconds?: int`<br>`end_timer_started_at?: string`<br>`correct_indices?: list[int]`<br>`poll_running: bool`<br>`votes: dict[str, HostPollVote{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`option_indices:list[int]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`voted_at:string`<br>`}]`<br>`queue: PollQueueStatus{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`pending:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`current?:dict[str, any]`<br>`}` |
| Host reveals correct answers and awards scores.<br>`PUT /api/{session_id}/host/poll/correct` | `correct_indices: list[int]` | - |
| Host ends the poll.<br>`POST /api/{session_id}/host/poll/end` | - | - |
| Host starts a countdown timer to end the poll.<br>`POST /api/{session_id}/host/poll/end/timer` | `seconds?: int` | - |
| Create Poll, host manually creates and immediately opens a new poll.<br>`POST /api/{session_id}/host/poll/manual/submit` | `question: string`<br>`options: list[string]`<br>`multi: bool`<br>`correct_count?: int` | - |
| Clear Queue<br>`DELETE /api/{session_id}/host/poll/queue` | - | - |
| Submit Questions, replace the entire poll queue with the submitted questions; typically called by AI submitting generated questions.<br>`POST /api/{session_id}/host/poll/queue` | `questions: list[PollQueueQuestion{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`question:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`options:list[string]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`correct_indices:list[int]`<br>`}]` | - |
| Skip Current<br>`POST /api/{session_id}/host/poll/queue/skip` | - | - |
| Submit Current<br>`POST /api/{session_id}/host/poll/queue/submit` | - | - |

### Host WS
| Message | Payload |
| --- | --- |
| Poll queue changed — host should GET /poll/queue to refresh<br>`poll_queue_updated` | - |
| Real-time vote tally while poll is open<br>Host-only event; participants do not receive live vote tallies.<br>Only total voted count is sent to avoid influencing participants.<br>`vote_update` | `voted_count: int  # total number of participants who have voted so far` |

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
| Q&A list changed (new question, upvote, edit, delete)<br>`qa_updated` | `questions: list[QAQuestion{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`author_uuid:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`upvoter_uuids:list[string]  # Client computes is_own and has_upvoted locally from its own UUID`<br>&nbsp;&nbsp;&nbsp;&nbsp;`answered:bool`<br>&nbsp;&nbsp;&nbsp;&nbsp;`timestamp:number`<br>`}]` |

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
| Q&A list changed (same structure as participant)<br>`qa_updated` | `questions: list[QAQuestion{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`author_uuid:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`upvoter_uuids:list[string]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`answered:bool`<br>&nbsp;&nbsp;&nbsp;&nbsp;`timestamp:number`<br>`}]` |

## Feature: Code Review

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Update Selection, participant sets their selected lines (full replacement).<br>`PUT /api/participant/codereview/selection` | `lines?: list[int]` | - |

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
| Full debate state snapshot<br>`debate_updated` | `statement?: string`<br>`phase?: 'side_selection' \| 'arguments' \| 'ai_cleanup' \| 'prep' \| 'live_debate' \| 'ended'`<br>`sides?: dict[str, string]  # uuid → "for"\|"against"`<br>`arguments?: list[DebateArgument{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`author_uuid:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`side:'for' \| 'against'`<br>&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`upvoters:list[string]`<br>&nbsp;&nbsp;&nbsp;&nbsp;`ai_generated:bool`<br>&nbsp;&nbsp;&nbsp;&nbsp;`merged_into?:string`<br>`}]`<br>`champions?: dict[str, string]  # "for"\|"against" → uuid`<br>`auto_assigned?: list[string]`<br>`first_side?: string`<br>`round_index?: int`<br>`round_timer_seconds?: int`<br>`round_timer_started_at?: string` |
| A timed debate round started<br>`debate_timer` | `round_index: int`<br>`seconds: int`<br>`started_at: string` |
| `debate_round_ended` | - |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Host launches a debate with a statement.<br>`POST /api/{session_id}/host/debate` | `statement: string` | - |
| Receive Ai Result, manual/skip AI result — host posts AI cleanup results directly.<br>`POST /api/{session_id}/host/debate/ai-result` | `merges?: list[DebateAiMerge{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`keep_id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`remove_ids?:list[string]`<br>`}]`<br>`cleaned?: list[DebateAiCleaned{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>`}]`<br>`new_arguments?: list[DebateAiNewArgument{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`side:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>`}]` | - |
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
| Leaderboard overlay shown with top positions<br>`leaderboard_revealed` | `positions: list[LeaderboardPosition{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`rank:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`name:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`score:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`avatar:string`<br>`}]` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Show Leaderboard<br>`POST /api/{session_id}/host/leaderboard/show` | - | `entries: list[LeaderboardPosition{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`rank:int`<br>&nbsp;&nbsp;&nbsp;&nbsp;`name:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`score:int`<br>`}]` |
| Reset Scores<br>`DELETE /api/{session_id}/host/scores` | - | - |

## Feature: Emoji Reactions

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Emoji Reaction, participant sends an emoji reaction.<br>`POST /api/participant/emoji/reaction` | `emoji: string` | - |

### Participant WS
| Message | Payload |
| --- | --- |
| Cumulative emoji reaction counts for the current talk session<br>`emoji_counters_updated` | `counters: dict[str, int]  # Map of emoji character to total reaction count` |

### Host WS
| Message | Payload |
| --- | --- |
| Participant sent an emoji reaction — floating animation on host screen<br>`emoji_reaction` | `emoji: string` |

### Addons WS
| Message | Payload |
| --- | --- |
| Relay emoji reaction to desktop overlay for animation<br>`display_emoji` | `emoji: string  # Emoji character to animate`<br>`count: int  # Number of times to show the animation` |

## Feature: Paste & File Upload

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Participant pastes text to be seen by host.<br>`POST /api/participant/paste` | `text: string` | - |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Pastes, return all pending paste entries grouped by participant uuid.<br>`GET /api/{session_id}/host/pastes` | - | `pastes?: dict[str, list[PasteEntry{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`id:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>`}]]` |
| Mark Uploaded File Seen<br>`POST /api/{session_id}/host/uploads/seen` | `uuid: string`<br>`file_id: string` | - |

### Host WS
| Message | Payload |
| --- | --- |
| Participant submitted a text paste<br>`paste_received` | `uuid: string  # Participant UUID who submitted the paste`<br>`id: string  # Paste ID`<br>`text: string` |
| Participant uploaded a file (daemon has downloaded it to session folder)<br>`file_uploaded` | `uuid: string  # Participant UUID who uploaded the file`<br>`id: string  # File ID`<br>`filename: string`<br>`size: int  # File size in bytes`<br>`disk_path: string  # Absolute path on the host's disk where the file was saved by the daemon` |

### Railway REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Download Uploaded File, daemon downloads a participant-uploaded file from Railway's temporary storage; called after Railway notifies the daemon via WebSocket that a new file is ready for download.<br>`GET /upload/{file_id}` | - | `application/octet-stream: string` |
| Acknowledge File Download, daemon confirms it has downloaded and persisted the file to local disk; railway deletes its temporary copy upon receiving this acknowledgement.<br>`POST /upload/{file_id}/ack` | `disk_path: string  # Absolute local path where the daemon saved the file.` | `ok?: bool` |

### Railway WS
| Message | Payload |
| --- | --- |
| Railway notifies daemon that a participant has uploaded a file<br>`file_ready_for_download` | `file_id: int`<br>`uuid: string  # Participant UUID who uploaded the file`<br>`filename: string`<br>`size: int  # File size in bytes`<br>`session_id: string` |

## Feature: Notes, Summary & Agenda

### Participant REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Agenda, serve the agenda .docx as base64-encoded JSON (survives WS proxy).<br>`GET /api/participant/agenda` | - | `data: string`<br>`filename: string` |
| Get Notes<br>`GET /api/participant/notes` | - | `notes_content?: string` |
| Get Summary<br>`GET /api/participant/summary` | - | `points?: list[SummaryPoint{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`source:string`<br>`}]`<br>`raw_markdown?: string`<br>`updated_at?: string` |

### Participant WS
| Message | Payload |
| --- | --- |
| Notes file changed — mtime timestamp updated<br>`notes_updated` | `updated_at?: string  # ISO timestamp of notes file mtime` |
| AI summary file changed — mtime timestamp updated<br>`summary_updated` | `updated_at?: string  # ISO timestamp of ai-summary.md mtime` |

### Host REST
| Endpoint | Request | Response |
| --- | --- | --- |
| Get Host Notes, return current session notes content.<br>`GET /api/{session_id}/host/notes` | - | `notes_content?: string` |
| Get Host Summary, return summary points, raw markdown, and updated_at timestamp.<br>`GET /api/{session_id}/host/summary` | - | `points?: list[SummaryPoint{`<br>&nbsp;&nbsp;&nbsp;&nbsp;`text:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`source:string`<br>`}]`<br>`raw_markdown?: string`<br>`updated_at?: string` |

### Host WS
| Message | Payload |
| --- | --- |
| Notes file changed — mtime timestamp updated<br>`notes_updated` | `updated_at?: string  # ISO timestamp of notes file mtime` |
| AI summary file changed — mtime timestamp updated<br>`summary_updated` | `updated_at?: string  # ISO timestamp of ai-summary.md mtime` |

### Railway WS
| Message | Payload |
| --- | --- |
| Railway instructs daemon to force-generate a summary immediately<br>`summary_force` | - |
| Railway instructs daemon to reset summary state entirely<br>`summary_full_reset` | - |

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

## Feature: Infrastructure

### Railway WS
| Message | Payload |
| --- | --- |
| Railway proxies a participant REST request to the daemon for processing<br>`proxy_request` | `id: string  # Correlation ID to match with proxy_response`<br>`method: string  # HTTP method (GET, POST, etc.)`<br>`path: string  # Request path forwarded from the participant`<br>`body?: string  # JSON-encoded request body`<br>`headers?: dict[str, string]  # Forwarded request headers`<br>`participant_id?: string  # UUID of the participant who made the original request` |
| Daemon sends its build timestamp so Railway can detect version drift<br>`code_timestamp` | `timestamp: int  # Unix timestamp of the daemon build` |
| Daemon asks Railway to forward an event to all participants in the session<br>Wrapper message — inner event payload is a participant WS message<br>`broadcast` | `event: dict  # Participant WS message payload to broadcast` |
| Daemon returns the result of a proxied participant REST request<br>`proxy_response` | `id: string  # Correlation ID matching the original proxy_request`<br>`status: int  # HTTP status code`<br>`body: string  # Response body (JSON or plain text)`<br>`content_type: string  # MIME type of the response body` |
| Daemon keepalive ping to Railway<br>`daemon_ping` | - |

## Feature: Intellij

### Addons WS
| Message | Payload |
| --- | --- |
| Currently open file in IntelliJ changed<br>`git_file_opened` | `url: string  # Git remote URL of the project`<br>`branch: string  # Current git branch`<br>`file: string  # Filename of the open file`<br>`file_url?: string  # Full GitHub/GitLab URL to the file (omitted when filename is ambiguous)` |
