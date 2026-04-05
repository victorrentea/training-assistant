## ADDED Requirements

### Requirement: Daemon reads slide activity data from daily activity file
The daemon SHALL parse `activity-slides-<YYYY-MM-DD>.md` from `TRANSCRIPTION_FOLDER` to obtain per-slide time data. Each line matching the pattern `HH:MM:SS DeckName - s<num>:<duration>[, ...]` represents one activity period. The daemon SHALL use the **last** occurrence of each `(timestamp, deck)` pair in the file as the authoritative data for that period.

#### Scenario: File contains multiple updates for the same period
- **WHEN** the file has several lines with the same `HH:MM:SS` and deck name (live updates)
- **THEN** only the last such line is used; earlier lines for that pair are discarded

#### Scenario: File does not exist or is unreadable
- **WHEN** `activity-slides-<date>.md` is absent or cannot be opened
- **THEN** the reader SHALL return an empty list without raising an exception

---

### Requirement: Daemon filters activity entries to the current session's active intervals
When an active session with `started_at` is known, the daemon SHALL include only activity-period entries whose `HH:MM:SS` timestamp falls at or after `session.started_at` and is not fully within a closed pause interval. If no session is active, the daemon SHALL include all entries from today's file.

#### Scenario: Session active — old activity period excluded
- **WHEN** the file contains a period starting at 09:00 and the session started at 14:00
- **THEN** the 09:00 period is excluded from the returned log

#### Scenario: Session active — paused interval excluded
- **WHEN** the file contains a period at 15:30 and the session was paused from 15:00 to 16:00
- **THEN** the 15:30 entry is excluded from the returned log

#### Scenario: No active session — all entries included
- **WHEN** no session state is available
- **THEN** all entries from the current day's file are returned

---

### Requirement: Daemon exposes slides_log stats in host state
The daemon SHALL include `slides_log`, `slides_log_deep_count`, and `slides_log_topic` in the response of `GET /{sid}/host/state`.

- `slides_log`: flat list of `{file, slide, seconds_spent}` dicts derived from the activity file
- `slides_log_deep_count`: count of unique `(file, slide)` pairs in `slides_log`
- `slides_log_topic`: `presentation_name` from `misc_state.slides_current` if set, else the `file` of the highest-`seconds_spent` entry, else `null`

#### Scenario: Host fetches state after a session with slide activity
- **WHEN** host calls `GET /{sid}/host/state` after slides were shown during the session
- **THEN** response includes non-empty `slides_log`, correct `slides_log_deep_count`, and a non-null `slides_log_topic`

#### Scenario: Host fetches state before any slide is shown today
- **WHEN** no activity file entry falls within the session time window
- **THEN** response includes `slides_log: []`, `slides_log_deep_count: 0`, `slides_log_topic: null`
