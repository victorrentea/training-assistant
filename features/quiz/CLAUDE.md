# Quiz

## Purpose
Integration point between the host UI and the training daemon for AI-generated quiz questions. The host requests a quiz (transcript-based or topic-based); the daemon generates it and posts a preview; the host can refine individual questions or options before publishing as a poll.

## Endpoints
- `POST /api/quiz-request` — host requests a quiz; stores request for daemon pickup; sets status to "requested"
- `GET /api/quiz-request` — daemon polls for pending request (clears on read); also returns session context
- `POST /api/quiz-status` — daemon updates status message + optional slides list
- `POST /api/quiz-preview` — daemon posts generated question preview (question, options, correct_indices)
- `DELETE /api/quiz-preview` — clear the current preview
- `POST /api/quiz-refine` — host requests regeneration of a specific question or option
- `GET /api/quiz-refine` — daemon polls for pending refine request (clears on read)

## State Fields
Fields in `AppState` owned by this feature:
- `quiz_request: dict | None` — `{minutes, topic}` pending for daemon
- `quiz_refine_request: dict | None` — `{target}` pending for daemon (e.g. `"question"` or `"opt0"`)
- `quiz_status: dict | None` — `{status, message}` shown in host UI
- `quiz_preview: dict | None` — `{question, options[], multi, correct_indices[], source, page}`
- `daemon_last_seen: datetime | None` — last daemon ping time
- `daemon_session_folder: str | None` — current session folder path
- `daemon_session_notes: str | None` — session notes
- `slides: list[dict]` — slides list from daemon (used for quiz source attribution)

## Design Decisions
- `correct_indices` are stored in the preview for host review only — they are never sent to participants via broadcast; the host must use `PUT /api/poll/correct` to reveal them.
- Two modes: transcript mode (last N minutes) or topic mode (free-form topic string).
- The daemon clears `quiz_request` on first read (one-shot handshake).
- `GET /api/quiz-request` also updates `daemon_last_seen` (used as daemon heartbeat).
- Broadcasts `quiz_status` via WebSocket on every status/preview update so host sees live progress.
