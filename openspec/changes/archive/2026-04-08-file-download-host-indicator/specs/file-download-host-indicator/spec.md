## ADDED Requirements

### Requirement: Host sees download icon after file lands on disk
After the daemon downloads a participant's uploaded file to the session folder, the system SHALL persist the uploaded file indicator in the active session state and the host browser SHALL display a blinking download icon next to that participant's name in the participant list.

#### Scenario: Icon appears after successful daemon download
- **WHEN** the daemon downloads a file and Railway broadcasts `file_uploaded` with `disk_path`
- **THEN** daemon stores the indicator metadata (`uuid`, `file_id`, `filename`, `disk_path`, `dismissed=false`) in session state
- **THEN** the host participant list shows a blinking download icon next to the sender's name

#### Scenario: Host resume restores indicators from session state
- **WHEN** the host reconnects or reopens the same active session
- **THEN** the host state snapshot (proxied by Railway) includes non-dismissed uploaded file indicators from daemon session state
- **THEN** the participant list renders the same download icons without requiring a new upload event

#### Scenario: Icon blinks until acknowledged
- **WHEN** the download icon is shown
- **THEN** it SHALL animate (blink/pulse) continuously until the host clicks it

### Requirement: Hover shows local disk path
The download icon SHALL display a tooltip on hover containing the full absolute path where the file was saved on the host's disk.

#### Scenario: Tooltip on hover
- **WHEN** the host hovers over the download icon
- **THEN** a tooltip appears showing the full disk path (e.g. `/Users/victor/.../uploads/report.pdf`)

### Requirement: Click copies path and dismisses icon
Clicking the download icon SHALL copy the full disk path to the clipboard and immediately remove the icon from the participant list, and dismissal SHALL be persisted in session state.

#### Scenario: Click copies and dismisses
- **WHEN** the host clicks the download icon
- **THEN** the disk path is copied to the clipboard
- **THEN** the file indicator is marked dismissed in session state
- **THEN** the icon disappears from the participant list

#### Scenario: Icon does not reappear after dismissal
- **WHEN** the host has already clicked the download icon for a given file
- **THEN** the icon SHALL NOT reappear for that file (dismissal is permanent for the session)

#### Scenario: Dismissed icon stays hidden after reconnect
- **WHEN** the host reconnects to the same active session after dismissing an indicator
- **THEN** the dismissed indicator remains hidden

### Requirement: Download icon style matches participant upload button
The icon SHALL use the same SVG style as the participant-side upload button (viewBox 0 0 20 20, stroke-based, round line caps/joins, downward arrow shape).

#### Scenario: Visual consistency
- **WHEN** the download icon is rendered in the host participant list
- **THEN** it uses the same SVG stroke style as the upload icon on the participant screen, with a downward arrow direction
