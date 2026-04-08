## MODIFIED Requirements

### Requirement: Session API documentation is contract-driven
API documentation for `session` capability in `API.md` SHALL be derived automatically from contracts and SHALL NOT be edited manually.

#### Scenario: Session endpoints appear from OpenAPI
- **WHEN** session operations exist in daemon OpenAPI
- **THEN** they appear automatically in Session Management section of `API.md`

#### Scenario: Session note updates propagate automatically
- **WHEN** `summary`/`description`/`x-doc-notes` changes on a session operation
- **THEN** the updated note appears in `API.md` on next generation
