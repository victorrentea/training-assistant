## ADDED Requirements

### Requirement: Broadcast participant names to all participants on any change
The system SHALL broadcast the current participant **names** to **all** participants on **any** roster change — join, rename, or leave — not just the participant count. This is net-new: today only the host receives the roster. The broadcast SHALL be a participant-facing message (e.g. `participant_names_updated`) carrying a list of **display names only**, sent on the participant broadcast channel.

#### Scenario: Names are broadcast on join
- **WHEN** a participant joins the session
- **THEN** the system SHALL broadcast the updated list of participant display names to all participants

#### Scenario: Names are broadcast on rename
- **WHEN** a participant changes their name
- **THEN** the system SHALL broadcast the updated list of participant display names to all participants

#### Scenario: Names are broadcast on leave
- **WHEN** a participant leaves the session
- **THEN** the system SHALL broadcast the updated list of participant display names to all participants

### Requirement: No UUIDs or stable ids in any participant-facing payload
Because a participant's identity is their `X-Participant-ID` UUID, and learning another participant's UUID would let one participant impersonate another (bypassing per-identity rate-limiting and identity), **no participant-facing WS or HTTP payload SHALL contain a UUID or any other stable per-user id.** The participant name broadcast SHALL carry display names only. The host-facing roster MAY continue to include UUIDs because the host is trusted.

#### Scenario: Name broadcast carries names only
- **WHEN** the system broadcasts the participant name list to participants
- **THEN** the payload SHALL contain display names only
- **AND** SHALL NOT contain any UUID or other stable per-user id

#### Scenario: Host roster may retain UUIDs
- **WHEN** the system sends the roster to the host
- **THEN** it MAY include UUIDs, because the host is a trusted recipient

### Requirement: Existing participant-facing payloads are audited for id leakage
All existing participant-facing WS/HTTP payloads SHALL be audited for any UUID or other stable per-user id, and any such id SHALL be stripped so no participant-facing payload leaks another participant's identity.

#### Scenario: Audit strips any leaked id
- **WHEN** an existing participant-facing payload is found to include a UUID or stable per-user id
- **THEN** that id SHALL be removed from the participant-facing payload
