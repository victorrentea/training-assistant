## ADDED Requirements

### Requirement: Participant bar shows notes count
The participant header Notes button SHALL display the non-empty line count when `notes_count > 0` and SHALL be disabled (greyed out, not clickable) when `notes_count == 0`.

#### Scenario: Notes present on page load
- **WHEN** the participant loads the page and `/state` returns `notes_count: 13`
- **THEN** the Notes button is enabled and its label includes `13`

#### Scenario: No notes on page load
- **WHEN** the participant loads the page and `/state` returns `notes_count: 0`
- **THEN** the Notes button is disabled

#### Scenario: WS update enables Notes button
- **WHEN** a `notes_updated {count: 7}` message arrives over WebSocket
- **THEN** the Notes button becomes enabled and its label shows `7`

#### Scenario: WS update triggers yellow flash
- **WHEN** a `notes_updated` message arrives over WebSocket (not on page load)
- **THEN** the Notes button label briefly flashes yellow

### Requirement: Participant bar shows summary count
The participant header Key Points button SHALL display the summary point count when `summary_count > 0` and SHALL be disabled when `summary_count == 0`.

#### Scenario: Summary present on page load
- **WHEN** the participant loads the page and `/state` returns `summary_count: 17`
- **THEN** the Key Points button is enabled and its label includes `17`

#### Scenario: No summary on page load
- **WHEN** the participant loads the page and `/state` returns `summary_count: 0`
- **THEN** the Key Points button is disabled

#### Scenario: WS update enables Key Points button
- **WHEN** a `summary_updated {count: 5}` message arrives over WebSocket
- **THEN** the Key Points button becomes enabled and its label shows `5`

#### Scenario: WS update triggers yellow flash
- **WHEN** a `summary_updated` message arrives over WebSocket (not on page load)
- **THEN** the Key Points button label briefly flashes yellow

### Requirement: Daemon broadcasts counts on file change
The daemon SHALL broadcast `notes_updated` and `summary_updated` WS messages to all participants and the host whenever the notes file or `ai-summary.md` changes on disk.

#### Scenario: Notes file changes
- **WHEN** the notes `.txt` file gains new non-empty lines
- **THEN** daemon broadcasts `notes_updated {count: <new non-empty line count>}`

#### Scenario: Summary file changes
- **WHEN** `ai-summary.md` gains or loses content
- **THEN** daemon broadcasts `summary_updated {count: <new point count>}`

#### Scenario: Daemon reconnects to Railway
- **WHEN** the daemon WebSocket to Railway reconnects
- **THEN** daemon broadcasts current `notes_updated` and `summary_updated` counts

### Requirement: Hermetic test covers count display and WS flash
A hermetic Docker test SHALL verify:
- Notes and Key Points buttons disabled when counts are zero
- Buttons enabled with correct count label after state load with non-zero counts
- Yellow flash CSS class applied when WS `notes_updated`/`summary_updated` message arrives
