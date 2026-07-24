## ADDED Requirements

### Requirement: Attendees file maintained in the session folder
The daemon SHALL maintain a Markdown file named `attendees.md` inside the active session folder (alongside `session-state.json`, notes, and other per-session files). The file SHALL list the session's attendees derived from the canonical participant enumerator, written atomically.

#### Scenario: Attendees file exists for an active session
- **WHEN** a session is active and has at least one named participant
- **THEN** the daemon SHALL ensure `attendees.md` exists in the active session folder
- **AND** its content SHALL reflect the current participant roster

### Requirement: Attendees file is always fully regenerated on name changes
Whenever a participant's name is set or changed — registration, rename, or leave — the daemon SHALL **fully regenerate the whole `attendees.md`** from the live roster. There SHALL be **no managed-region logic and no trainer-hand-edit preservation**: the file is a generated artifact rewritten from the roster each time.

#### Scenario: New participant appears after full regeneration
- **WHEN** a participant registers with a name
- **THEN** the daemon SHALL rewrite the whole `attendees.md` from the live roster, including that participant

#### Scenario: Renamed participant is reflected after full regeneration
- **WHEN** a participant changes their name
- **THEN** the daemon SHALL rewrite the whole `attendees.md` from the live roster with the new name

#### Scenario: No managed region is preserved
- **WHEN** the daemon regenerates `attendees.md`
- **THEN** it SHALL rewrite the entire file from the roster
- **AND** SHALL NOT attempt to preserve a managed region or prior hand edits

### Requirement: Attendees file header derived from session context
Because there is no structured session-level metadata, the `attendees.md` header SHALL be derived from the session folder name, the date(s) parsed from it, and an optional Google Drive URL when available.

#### Scenario: Header reflects the session
- **WHEN** the daemon generates `attendees.md`
- **THEN** the file SHALL include a header derived from the session folder name and its parsed date(s)

### Requirement: Attendees file is reset per session and distinguishes anonymous entries
At per-session (re)initialization, the daemon SHALL create or clear `attendees.md` for the newly active session so it does not carry stale attendees from a previous session. Anonymous (auto-assigned fictional) entries SHALL be distinguishable from confirmed real names.

#### Scenario: File is initialized on session (re)init
- **WHEN** a session is (re)initialized as the active session
- **THEN** the daemon SHALL create or reset `attendees.md` for that session

#### Scenario: Anonymous participants are distinguishable
- **WHEN** a participant joined anonymously with an auto-assigned fictional name
- **THEN** `attendees.md` SHALL make it possible to tell that entry is not a confirmed real name

### Requirement: Attendee names survive reconnect and restart
The real names shown in `attendees.md` SHALL round-trip through `participant_state`, `sync_from_restore`, and the `session-state.json` snapshot so that a regenerated `attendees.md` retains real names after reconnect or restart rather than reverting to fictional names.

#### Scenario: Real names persist across reconnect
- **WHEN** the daemon reconnects or restarts and regenerates `attendees.md`
- **THEN** the file SHALL still contain the participants' real names (not reverted to auto-assigned names)
