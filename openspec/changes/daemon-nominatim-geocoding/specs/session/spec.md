## ADDED Requirements

### Requirement: Participant state includes resolved city label
The session participant state SHALL include a `city` field per participant containing the human-readable resolved location label.

#### Scenario: Participant state serialized with city
- **WHEN** participant state is serialized (for WS broadcast or persistence)
- **THEN** it SHALL include a `cities` dict mapping participant UUID to resolved city string
- **AND** the `cities` dict SHALL be restored correctly on daemon restart from persisted state

#### Scenario: Host state update includes city
- **WHEN** the daemon broadcasts a `participant_location` or `participant_registered` event
- **THEN** the event payload SHALL include a `city` field (empty string if not yet resolved)
