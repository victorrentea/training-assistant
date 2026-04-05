## ADDED Requirements

### Requirement: Notes and Summary WS Freshness Notification
The daemon SHALL detect content updates for `ai-summary.md` and for the active session notes `*.txt` file, and SHALL emit a WebSocket notification to both participant and host channels when either document changes.

#### Scenario: Summary file change triggers WS notification
- **WHEN** `ai-summary.md` in the active session folder changes
- **THEN** daemon SHALL broadcast a WS event to participants and host with `document="summary"`
- **AND** the event SHALL include `non_empty_lines` equal to the count of non-empty lines in `ai-summary.md`

#### Scenario: Notes file change triggers WS notification
- **WHEN** the active session notes `*.txt` file changes
- **THEN** daemon SHALL broadcast a WS event to participants and host with `document="notes"`
- **AND** the event SHALL include `non_empty_lines` equal to the count of non-empty lines in that `*.txt` file

#### Scenario: Notification is freshness-only
- **WHEN** daemon emits the notes/summary WS notification
- **THEN** the WS payload SHALL NOT include full notes or full summary content
- **AND** host and participant clients SHALL continue to use existing notes/summary REST endpoints to fetch full document content
