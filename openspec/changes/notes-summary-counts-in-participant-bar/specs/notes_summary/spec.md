## MODIFIED Requirements

### Requirement: Participant state returns counts not content
The `/state` endpoint response SHALL include `notes_count` (integer, non-empty line count of the notes file) and `summary_count` (integer, number of parsed summary points) instead of `notes_content` (full text) and `summary_points` (full array).

#### Scenario: State includes notes_count
- **WHEN** participant calls `GET /{sid}/api/participant/state`
- **THEN** response contains `notes_count: <int>` and does NOT contain `notes_content`

#### Scenario: State includes summary_count
- **WHEN** participant calls `GET /{sid}/api/participant/state`
- **THEN** response contains `summary_count: <int>` and does NOT contain `summary_points`
