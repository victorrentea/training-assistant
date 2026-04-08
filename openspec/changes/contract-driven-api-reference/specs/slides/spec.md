## MODIFIED Requirements

### Requirement: Slides API documentation is contract-driven
API documentation for `slides` capability in `API.md` SHALL be derived automatically from contracts and SHALL NOT be edited manually.

#### Scenario: Slides REST and WS coverage
- **WHEN** slides endpoints and slides messages exist in contracts
- **THEN** all of them appear in Slides section of `API.md`

#### Scenario: Slides cache semantics notes are contract-sourced
- **WHEN** slides operational notes are defined in contract (`summary`/`description`/`x-doc-notes`)
- **THEN** those notes appear in Slides section of `API.md`
