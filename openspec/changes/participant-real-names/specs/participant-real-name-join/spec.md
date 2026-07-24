## ADDED Requirements

### Requirement: Join-time name gate with a single free-text field
Before a participant is connected to live activity, the system SHALL present a name screen with a **single free-text name input** (not first/last, no separate fields) whenever the server has **no committed name for this participant's UUID in the active session**. The input SHALL show ghost/placeholder text and be accompanied by a short hint line stating the name will be used to produce the attendance sheet. The typed name SHALL be stored as a single string in the existing participant `name` field.

#### Scenario: First-visit participant sees the single-field gate
- **WHEN** a participant opens a session URL and the server has no committed name for their UUID in the active session
- **THEN** the system SHALL show the single free-text name screen before establishing the live connection
- **AND** the input SHALL display placeholder text and a hint that the name is used for the attendance sheet

#### Scenario: No first/last split anywhere
- **WHEN** the participant provides a name at the gate
- **THEN** the system SHALL store it as a single string in the existing `name` field
- **AND** SHALL NOT split it into separate first-name and last-name fields in the UI, model, or storage

### Requirement: Enter button submits the typed name
The name screen SHALL provide an **Enter** control that is enabled **only when the input is non-empty** (whitespace-only counts as empty). Activating Enter SHALL submit the typed name and admit the participant to the live session.

#### Scenario: Enter is disabled on empty input
- **WHEN** the name input is empty or whitespace-only
- **THEN** the Enter control SHALL be disabled and the name SHALL NOT be submitted

#### Scenario: Enter submits the typed name and admits
- **WHEN** the participant types a non-empty name and activates Enter
- **THEN** the system SHALL register (first visit) or rename (already-registered) the participant with the typed name
- **AND** SHALL admit the participant to the live session

### Requirement: Anonymous button ignores the typed input
The name screen SHALL provide an **Anonymous** control (e.g. "Enter as anonymous") that **ignores whatever is typed** and admits the participant under an auto-assigned fictional name via the existing empty-body registration path. The control SHALL display a warning **on hover and as a tooltip** that the participant might not appear correctly in the attendance sheet.

#### Scenario: Anonymous ignores the typed text and assigns a fictional name
- **WHEN** the participant has typed some text and activates the Anonymous control
- **THEN** the system SHALL disregard the typed text
- **AND** SHALL register the participant with an auto-assigned fictional name
- **AND** SHALL admit them to the live session

#### Scenario: Anonymous control warns about attendance
- **WHEN** the participant hovers the Anonymous control
- **THEN** the system SHALL show a warning (hover and tooltip) that they might not appear correctly in the attendance sheet

### Requirement: Gate visibility keyed off a committed name for the UUID
The gate SHALL be shown exactly when the server has **no committed name for this participant's UUID in the active session**, so that it appears on first visit and on next-day / new-session joins, and is **skipped on same-session reconnect** for a participant who already has a committed name (real or anonymous).

#### Scenario: Same-session reconnect skips the gate
- **WHEN** a participant reconnects within the same session and the server returns a committed name for their UUID
- **THEN** the system SHALL admit them without showing the name screen

#### Scenario: Gate reappears on a new session
- **WHEN** the participant state has been reset for a new session (so the UUID is no longer known)
- **THEN** the system SHALL show the name screen again on the next join

#### Scenario: Gate fails open on error
- **WHEN** registration or rejoin fails while the gate is shown
- **THEN** the system SHALL offer a retry or the anonymous path rather than trapping the participant in a dead end

### Requirement: Name field capacity accommodates full names
The participant `name` field SHALL accept names up to at least 64 characters (raised from the prior 32-character limit) so realistic full names are not truncated.

#### Scenario: A long full name is preserved
- **WHEN** a participant submits a name whose length exceeds 32 characters but is at most 64
- **THEN** the system SHALL store the full name without truncating it to 32 characters

### Requirement: Test and pre-seed hooks remain functional
The gate SHALL preserve the existing `?as=Name` pre-seed hook and hermetic sequence tests: a pre-seeded name SHALL satisfy the gate without requiring the name screen to be shown interactively.

#### Scenario: Pre-seeded name bypasses the interactive gate
- **WHEN** a participant opens the session with a pre-seeded name (e.g. `?as=Alice`)
- **THEN** the system SHALL register that name and admit the participant without showing the name screen
