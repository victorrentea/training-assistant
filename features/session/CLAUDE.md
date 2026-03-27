# Session

## Purpose
Manages session lifecycle (start, end, pause, resume, nested talks) and provides the daemon-facing sync endpoint for persisting full session state to disk. Also serves transcript interval queries.

## Endpoints
- `POST /api/session/start` — host starts a new session (name)
- `POST /api/session/end` — host ends the current session
- `POST /api/session/pause` — host pauses session (e.g. lunch break)
- `POST /api/session/resume` — host resumes a paused session
- `POST /api/session/start_talk` — host starts a nested talk (conference mode)
- `POST /api/session/end_talk` — host ends nested talk
- `POST /api/session/create` — host creates a new session folder
- `PATCH /api/session/rename` — host renames current session
- `GET /api/session/request` — daemon polls for pending session request (clears on read)
- `POST /api/session/sync` — daemon syncs session state back to backend (session stack, key points, full state restore)
- `POST /api/session/timing_event` — daemon notifies backend of a timing event (e.g. "5 min left"); forwarded to host WS
- `GET /api/session/interval-lines.txt` — returns raw transcript lines for a time window (start/end ISO params)
- `GET /api/session/snapshot` — returns full serializable AppState for daemon to persist every 5s
- `GET /api/session/folders` — returns list of session folders from SESSIONS_FOLDER

## State Fields
Fields in `AppState` owned by this feature:
- `session_request: dict | None` — pending action for daemon `{action, name?}`
- `session_main: dict | None` — current main session info `{name, status, start_time, ...}`
- `session_talk: dict | None` — active nested talk info
- `paused_participant_uuids: set[str]` — UUIDs from the paused session (rejected on reconnect during pause)

## Design Decisions
- Session commands use a one-shot request pattern: host writes to `session_request`, daemon reads and clears it via `GET /api/session/request`.
- `POST /api/session/sync` handles the full state restore case (daemon passes `session_state` JSON), allowing the backend to recover participant names, scores, and activity state after a restart.
- `paused_participant_uuids` prevents old-session participants from connecting to a new/resumed session.
- `GET /api/session/snapshot` is the daemon's source of truth for persistence — called every 5s.
- Transcript interval endpoint reads from normalized `YYYY-MM-DD transcription.txt` files; requires `TRANSCRIPTION_FOLDER` env var.
