## ADDED Requirements

### Requirement: API reference SHALL be generated exclusively from daemon contracts
The system SHALL generate `API.md` only from `docs/openapi.yaml`, `docs/participant-ws.yaml`, and `docs/host-ws.yaml`, without manual text insertion in output.

#### Scenario: Deterministic generation
- **WHEN** the generator runs twice with no contract changes
- **THEN** `API.md` output is byte-for-byte identical

### Requirement: Every REST operation SHALL declare feature classification explicitly
Each OpenAPI operation in daemon scope SHALL declare `x-feature` in exported OpenAPI schema.

#### Scenario: Missing REST x-feature is rejected
- **WHEN** a REST operation has no `x-feature`
- **THEN** documentation verification SHALL fail and SHALL list the exact missing operations

### Requirement: Every WS message SHALL declare feature classification explicitly
Each AsyncAPI message in `docs/participant-ws.yaml` and `docs/host-ws.yaml` SHALL declare `x-feature`.

#### Scenario: Missing WS x-feature is rejected
- **WHEN** an AsyncAPI message has no `x-feature`
- **THEN** documentation verification SHALL fail and SHALL list the exact missing messages

### Requirement: Contract notes SHALL be exported in generated API reference
The generator SHALL include notes from `x-doc-notes`, `summary`, and `description` for endpoints and WS messages in output.

#### Scenario: REST notes export
- **WHEN** a REST operation has `x-doc-notes` and/or `description`
- **THEN** the corresponding endpoint section in `API.md` includes those notes

#### Scenario: WS notes export
- **WHEN** a WS message has `x-doc-notes` and/or `summary`
- **THEN** the corresponding message section in `API.md` includes those notes

### Requirement: Generated API reference SHALL remain synchronized in verification pipeline
The repository SHALL include automated verification that detects when committed `API.md` no longer matches current contracts.

#### Scenario: Stale committed document
- **WHEN** contracts change but committed `API.md` is not regenerated
- **THEN** verification SHALL fail and SHALL indicate the exact regeneration command
