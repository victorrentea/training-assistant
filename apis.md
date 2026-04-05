# API Reference (Reviewed)

Architecture:
```
Participant Browser ── REST ──> Railway (proxy) ── WS ──> Daemon
                    <── WS (receive-only) ──────────────<

Host Browser ── REST ──────────────────────────────────> Daemon localhost:8081
             <── WS (receive-only) ────────────────────<
```

All participant REST: `/{sid}/api/participant/...` with `X-Participant-ID` header.
All host REST: `/api/{sid}/host/...` on daemon localhost.

---

## Feature: Session Management

### Participant
**Participant Browser → Daemon REST:** (none — joins by URL)

**Daemon → Participant Browser WS:** (none — on session end, Railway closes WS connections for that sid; participant JS enters retry loop with backoff: 1s→3s→5s then 5s±1s jitter, showing "Waiting for host to connect")

### Host
**Host Browser → Daemon REST:**
| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/api/session/start` | `{name, type}` | `{ok, session_id}` |
| POST | `/api/session/resume` | `{folder}` | `{ok, session_id}` |
| POST | `/api/session/end` | — | `{ok}` |
| GET | `/api/session/folders` | — | `{folders[]}` |
| GET | `/api/session/active` | — | `{session_id}` or `null` |

`start` creates a new session folder (empty slate). `resume` resumes an existing folder, restoring state from `.session-state.json`. Session endpoints are global (no `{sid}` prefix). On end, daemon sends `set_session_id` with null to Railway, which drops all participant WS connections for that sid.

**Daemon → Host Browser WS:** (none — host triggered the actions)

### State
```
active_session_id: str | null    # the 6-char code (THE one string Railway needs)
session_name: str | null         # display name
```

---

## Feature: Slides

### Participant
**Participant Browser → Daemon REST** (proxied by Railway):
| Method | Path | Body | Response |
|--------|------|------|----------|
| GET | `/{sid}/api/slides` | — | `{slides[], cache_status: {slug→{status, size_bytes}}}` — daemon is source of truth; each deck includes `size_mb: float` |
| GET | `/{sid}/api/slides/check/{slug}` | — | 200 OK (PDF is fresh and on Railway disk) or 503 (timed out after 30s) — participant MUST call this before downloading |
| GET | `/{sid}/api/slides/download/{slug}` | — | PDF binary served directly by Railway from disk (max 100MB) — only call after /check returns 200 |

`/check` flow: daemon responds 200 immediately if PDF is fresh; otherwise sends `download_pdf` to Railway via WS and holds the response open until Railway confirms download complete (or 30s → 503). Participant shows "Retry" on 503 — no auto-retry. If Railway finishes after the timeout, daemon still receives `pdf_download_complete` and broadcasts `slides_cache_status` to all participants — participant UI clears the "Retry" state and shows the green cached indicator automatically.

Current slide is included in the initial state from `GET /{sid}/api/participant/state` and tracked via WS events continuously — no separate current-slide endpoint needed.

**Daemon → Participant Browser WS:**
- `slides_current` — `{slides_current}` — when host navigates slides
- `slides_cache_status` — `{slides_cache_status: {slug→{status, size_bytes}}}` — download progress updates

### Host
**Host Browser → Daemon REST:**
Slides managed via daemon's session tooling, not direct host REST calls.

**Daemon → Host Browser WS:** (none relevant)

### Internal: Daemon ↔ Railway WS messages
| Direction | Type | Payload | Purpose |
|-----------|------|---------|---------|
| Daemon → Railway | `download_pdf` | `{slug, drive_export_url}` | Daemon instructs Railway to pull PDF from GDrive |
| Railway → Daemon | `pdf_download_complete` | `{slug, status: "ok"\|"error"}` | Railway notifies daemon download finished |

### State
```
slides_cache_status: dict[str, dict]   # slug → {status: "not_cached"|"downloading"|"cached"|"stale"|"error", size_bytes, downloaded_at}
```

**Daemon** owns this state and all caching decisions (fingerprint polling, staleness detection, download coordination). Railway executes GDrive HTTP pulls on daemon's instruction and stores PDFs on disk. Railway cannot self-initiate downloads.

Note: slide list includes `size_mb` for each deck so participants see expected download size and traffic.

---

## Feature: Activity Switching

### Participant
**Participant Browser → Daemon REST:** (none — host controls)

**Daemon → Participant Browser WS:**
- `activity_updated` — `{current_activity}`

### Host
**Host Browser → Daemon REST:**
| Method | Path | Body | Response |
|--------|------|------|----------|
| PUT | `/api/{sid}/host/activity` | `{activity}` | `{ok}` |

`activity`: `"none"` | `"poll"` | `"wordcloud"` | `"qa"` | `"codereview"` | `"debate"`

**Daemon → Host Browser WS:** (none — host triggered it)

### State
```
current_activity: str           # "none"|"poll"|"wordcloud"|"qa"|"codereview"|"debate"
```

---

## Feature: Identity

### Participant
**Participant Browser → Daemon REST:**
| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/{sid}/api/participant/register` | `{}` | `{name, avatar}` |
| PUT | `/{sid}/api/participant/name` | `{name}` | 200 or 409 (no body) |
| POST | `/{sid}/api/participant/avatar/roll` | `{rejected[]}` | `{ok, avatar}` |
| PUT | `/{sid}/api/participant/location` | `{location}` | `{ok}` |
| GET | `/{sid}/api/participant/state` | — | Full personalized state |

All carry `X-Participant-ID: <uuid>` header. UUID generated by browser, stored in `localStorage`.

**Daemon → Participant Browser WS:**
- `participant_updated` — `{count}`

### Host
**Host Browser → Daemon REST:**
| Method | Path | Response |
|--------|------|----------|
| GET | `/api/{sid}/host/state` | Full state with participant list |

**Daemon → Host Browser WS:**
- `participant_updated` — `{count, participants[{uuid, name, score, location, avatar}]}`

### State
```
participants: dict[str, Participant]
  Participant:
    name: str
    avatar: str
    location: str | null
    universe: str | null        # conference mode only (optional)
mode: str                       # "workshop" | "conference"
```

### Page load flow
1. Generate/retrieve UUID from `localStorage`
2. `POST /{sid}/api/participant/register` → `{name, avatar}`
3. Connect WS `ws://host/ws/{sid}/{uuid}` (receive-only)
4. `GET /{sid}/api/participant/state` → full state → render
5. Track WS events for incremental updates
6. On WS disconnect → reconnect with backoff (1s→3s→5s then 5s±1s jitter) → re-fetch state

---

## Feature: Poll

### Participant
**Participant Browser → Daemon REST:**
| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/{sid}/api/participant/poll/vote` | `{option_ids: ["A"]}` | `{ok}` |

`option_ids` is always a list: single element for single-answer, multiple for multi-select. Vote is final.

**Daemon → Participant Browser WS:**
- `poll_opened` — `{poll: {id, question, options[], multi}}`
- `poll_closed` — `{}`
- `poll_correct_revealed` — `{correct_ids[]}`
- `poll_cleared` — `{}`
- `poll_timer_started` — `{seconds}`
- `scores_updated` — `{scores: {uuid→points}}`

### Host
**Host Browser → Daemon REST:**
| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/api/{sid}/host/poll` | `{question, options[], multi?}` | `{ok}` |
| DELETE | `/api/{sid}/host/poll` | — | `{ok}` |
| POST | `/api/{sid}/host/poll/open` | — | `{ok}` |
| POST | `/api/{sid}/host/poll/close` | — | `{ok}` |
| PUT | `/api/{sid}/host/poll/correct` | `{correct_ids[]}` | `{ok}` |
| POST | `/api/{sid}/host/poll/timer` | `{seconds}` | `{ok}` |

**Daemon → Host Browser WS:**
- `poll_ai_generated` — `{poll}` — AI quiz generator created a poll (host sees it before opening)
- `vote_update` — `{votes: {option_id→count}}` — real-time tally

### State
```
poll: dict | null               # {id, question, options[], multi}
active: bool
votes: dict[str, Vote]          # uuid → Vote
  Vote:
    option_ids: list[str]       # always a list; [] if no vote, ["A"] single, ["A","C"] multi
    voted_at: datetime
correct_ids: list[str] | null
timer_seconds: int | null
timer_started_at: datetime | null
```

---

## Feature: Word Cloud

### Participant
**Participant Browser → Daemon REST:**
| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/{sid}/api/participant/wordcloud/word` | `{word}` | `{ok}` |

Awards 200 points. Max 40 chars.

**Daemon → Participant Browser WS:**
- `wordcloud_updated` — `{words: {word→count}, word_order[], topic}`

### Host
**Host Browser → Daemon REST:**
| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/api/{sid}/host/wordcloud/word` | `{word}` | `{ok}` |
| POST | `/api/{sid}/host/wordcloud/topic` | `{topic}` | `{ok}` |
| POST | `/api/{sid}/host/wordcloud/clear` | — | `{ok}` |

**Daemon → Host Browser WS:**
- `wordcloud_updated` — same as participant

### State
```
words: dict[str, int]       # word → count
word_order: list[str]       # newest first
topic: str
```

---

## Feature: Q&A

### Participant
**Participant Browser → Daemon REST:**
| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/{sid}/api/participant/qa/submit` | `{text}` | `{ok}` |
| POST | `/{sid}/api/participant/qa/upvote` | `{question_id}` | `{ok}` |

Submit: 100pts. Upvote: 50pts to author + 25pts to voter. Can't upvote own. Server rejects duplicate upvotes.

**Daemon → Participant Browser WS:**
- `qa_updated` — `{questions: [{id, text, author_uuid, upvoter_uuids[], answered, timestamp}]}`

Participant JS computes `is_own` and `has_upvoted` locally using its UUID.

### Host
**Host Browser → Daemon REST:**
| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/api/{sid}/host/qa/submit` | `{text}` | `{ok}` |
| PUT | `/api/{sid}/host/qa/question/{id}/text` | `{text}` | `{ok}` |
| DELETE | `/api/{sid}/host/qa/question/{id}` | — | `{ok}` |
| PUT | `/api/{sid}/host/qa/question/{id}/answered` | — | `{ok}` |
| POST | `/api/{sid}/host/qa/clear` | — | `{ok}` |

**Daemon → Host Browser WS:**
- `qa_updated` — same structure (host sees all questions)

### State
```
questions: dict[str, Question]
  Question:
    id: str
    text: str
    author_uuid: str
    upvoter_uuids: set[str]
    answered: bool
    timestamp: float
```

---

## Feature: Code Review

### Participant
**Participant Browser → Daemon REST:**
| Method | Path | Body | Response |
|--------|------|------|----------|
| PUT | `/{sid}/api/participant/codereview/selection` | `{lines: [3, 7, 12]}` | `{ok}` |

Full replacement of selected lines. Only during "selecting" phase.

**Daemon → Participant Browser WS:**
- `codereview_opened` — `{snippet, language}`
- `codereview_selection_closed` — `{}`
- `codereview_line_confirmed` — `{line}`
- `codereview_cleared` — `{}`
- `scores_updated` — on confirm (200pts per selector)

### Host
**Host Browser → Daemon REST:**
| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/api/{sid}/host/codereview` | `{snippet, language?, smart_paste?}` | `{ok}` |
| PUT | `/api/{sid}/host/codereview/status` | `{open: false}` | `{ok, phase}` |
| PUT | `/api/{sid}/host/codereview/confirm-line` | `{line}` | `{ok}` |
| DELETE | `/api/{sid}/host/codereview` | — | `{ok}` |

Smart paste: Claude Haiku extracts code from LLM output. Max 50 lines.

**Daemon → Host Browser WS:**
- `codereview_selections_updated` — `{line_counts: {line→count}}` — host-only

### State
```
snippet: str | null
language: str | null
phase: str                          # "idle" | "selecting" | "reviewing"
selections: dict[str, set[int]]     # pid → selected line numbers
confirmed: set[int]                 # host-confirmed lines
```

---

## Feature: Debate

### Participant
**Participant Browser → Daemon REST:**
| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/{sid}/api/participant/debate/pick-side` | `{side}` | `{ok}` |
| POST | `/{sid}/api/participant/debate/argument` | `{text}` | `{ok}` |
| POST | `/{sid}/api/participant/debate/upvote` | `{argument_id}` | `{ok}` |
| POST | `/{sid}/api/participant/debate/volunteer` | `{}` | `{ok}` |

Side: "for" or "against". Argument: max 280 chars, 100pts. Upvote: 50pts to author (human only) + 25pts to voter. Volunteer as champion: 2500pts.

**Daemon → Participant Browser WS:**
- `debate_updated` — full debate state snapshot
- `debate_timer` — `{round_index, seconds, started_at}`
- `debate_round_ended` — `{}`
- `scores_updated` — on scoring actions

### Host
**Host Browser → Daemon REST:**
| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/api/{sid}/host/debate` | `{statement}` | `{ok}` |
| POST | `/api/{sid}/host/debate/reset` | — | `{ok}` |
| POST | `/api/{sid}/host/debate/close-selection` | — | `{ok}` |
| POST | `/api/{sid}/host/debate/force-assign` | — | `{ok}` |
| POST | `/api/{sid}/host/debate/phase` | `{phase}` | `{ok}` |
| POST | `/api/{sid}/host/debate/first-side` | `{side}` | `{ok}` |
| POST | `/api/{sid}/host/debate/round-timer` | `{round_index, seconds}` | `{ok}` |
| POST | `/api/{sid}/host/debate/end-round` | — | `{ok}` |
| POST | `/api/{sid}/host/debate/end-arguments` | — | `{ok}` |
| POST | `/api/{sid}/host/debate/ai-result` | `{merges[], cleaned[], new_arguments[]}` | `{ok}` |

**Daemon → Host Browser WS:** (none — host triggered the actions)

### State
```
statement: str | null
phase: str | null               # "side_selection"|"arguments"|"ai_cleanup"|"prep"|"live_debate"|"ended"
sides: dict[str, str]           # uuid → "for"|"against"
arguments: list[Argument]
  Argument:
    id: str
    author_uuid: str
    side: str
    text: str
    upvoters: set[str]
    ai_generated: bool
    merged_into: str | null
champions: dict[str, str]       # "for"|"against" → uuid
auto_assigned: set[str]         # uuids auto-assigned to balance sides
first_side: str | null          # which side speaks first
round_index: int | null
round_timer_seconds: int | null
round_timer_started_at: datetime | null
```

---

## Feature: Scores & Leaderboard

### Participant
**Participant Browser → Daemon REST:** (none — scores are side effects of other features)

**Daemon → Participant Browser WS:**
- `scores_updated` — `{scores: {uuid→points}}` — after any scoring action
- `leaderboard_revealed` — `{positions: [{rank, name, score, avatar}]}` — one-shot display, participant JS auto-hides on timer

### Host
**Host Browser → Daemon REST:**
| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/api/{sid}/host/leaderboard/show` | — | `{ok}` |
| DELETE | `/api/{sid}/host/scores` | — | `{ok}` |

**Daemon → Host Browser WS:**
- `leaderboard_revealed` — same as participant

### State
```
scores: dict[str, int]    # uuid → total points
```

---

## Feature: Emoji Reactions

### Participant
**Participant Browser → Daemon REST:**
| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/{sid}/api/participant/emoji/reaction` | `{emoji}` | `{ok}` |

Max 4 chars. Fire and forget.

**Daemon → Participant Browser WS:** (none)

### Host
**Host Browser → Daemon REST:** (none)

**Daemon → Host Browser WS:**
- `emoji_reaction` — `{emoji}` — floating animation on host screen + overlay

### State
None — not persisted.

---

## Feature: Quiz Generation

### Participant
**Participant Browser → Daemon REST:** (none — quiz creates a poll which participants interact with via Poll feature)

**Daemon → Participant Browser WS:**
- `quiz_status` — `{status, message}` — generation progress ("generating", "ready", "error")
- `quiz_preview` — `{question, options[], multi, correct_indices[]}` — preview for host before publishing

### Host
**Host Browser → Daemon REST:**
| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/api/{sid}/host/quiz-request` | `{minutes?, topic?}` | `{ok}` |
| DELETE | `/api/{sid}/host/quiz-preview` | — | `{ok}` |
| POST | `/api/{sid}/host/quiz-refine` | `{target}` | `{ok}` |

`minutes`: how many minutes of transcript to use. `topic`: optional focus topic. `target`: which part to regenerate ("question", "opt1", "opt2", etc.).

**Daemon → Host Browser WS:**
- `quiz_status` — generation progress
- `quiz_preview` — preview for host review

### State
Quiz is ephemeral — daemon generates from transcript, publishes as a poll. No persistent quiz state beyond the preview.

---

## Feature: Paste & File Upload

### Participant
**Participant Browser → Daemon REST:**
| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/{sid}/api/participant/paste` | `{text}` | `{ok}` |
| POST | `/{sid}/api/participant/upload` | multipart file | `{ok, file_id}` |

Paste: 100KB max. Upload: participant screenshots/files (max 100MB). Upload goes to Railway first, then Railway notifies daemon to download the file. Daemon stores it in `{session_folder}/uploads/`.

**Daemon → Participant Browser WS:** (none)

### Host
**Host Browser → Daemon REST:**
| Method | Path | Body | Response |
|--------|------|------|----------|
| GET | `/api/{sid}/host/pastes` | — | `{pastes: {uuid→[{id, text}]}}` |
| GET | `/api/{sid}/host/uploads` | — | `{uploads: {uuid→[{id, filename, size}]}}` |
| GET | `/api/{sid}/host/uploads/{file_id}` | — | file binary |

**Daemon → Host Browser WS:**
- `paste_received` — `{uuid, id, text}` — host notified of new paste
- `file_uploaded` — `{uuid, id, filename, size}` — host notified of new upload

### State
```
paste_texts: dict[str, list[dict]]    # uuid → [{id, text}]
uploads: dict[str, list[dict]]        # uuid → [{id, filename, size, path}] — files on disk in session_folder/uploads/
```

### Upload flow
1. Participant uploads file to Railway (`POST /{sid}/api/participant/upload`)
2. Railway stores temporarily, sends WS notification to daemon: `{type: "file_uploaded", uuid, file_id, filename, size, download_url}`
3. Daemon downloads file from Railway immediately, stores in `{session_folder}/uploads/{file_id}`
4. Daemon sends `file_uploaded` event to host via WS
5. Railway deletes temporary file after daemon confirms download
6. Host can view/download files from daemon via `GET /api/{sid}/host/uploads/{file_id}`

---

## Feature: Notes & Summary

### Participant
**Participant Browser → Daemon REST:**
| Method | Path | Body | Response |
|--------|------|------|----------|
| GET | `/{sid}/api/participant/notes` | — | `{notes_content}` |
| GET | `/{sid}/api/participant/summary` | — | `{points[], raw_markdown, updated_at}` |

Notes and summary are files on disk in the session folder. Daemon reads them on request.

**Daemon → Participant Browser WS:** (none — participant fetches on demand)

### Host
**Host Browser → Daemon REST:**
| Method | Path | Response |
|--------|------|----------|
| GET | `/api/{sid}/host/notes` | `{notes_content}` |
| GET | `/api/{sid}/host/summary` | `{points[], raw_markdown, updated_at}` |

Host can open notes/summary in the host panel UI.

**Daemon → Host Browser WS:** (none)

### State
None persisted in memory — read from disk:
- `{session_folder}/notes.md` — session notes
- `{session_folder}/summary.json` — key points + raw markdown

---

## Cross-cutting: Reload

**Daemon → Participant Browser WS:**
- `reload` — `{}` — daemon synced static files, browser should reload

**Daemon → Host Browser WS:**
- `reload` — `{}` — same as participant
