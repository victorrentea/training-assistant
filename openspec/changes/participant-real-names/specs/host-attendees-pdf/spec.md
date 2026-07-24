## ADDED Requirements

> NOTE: This capability is LATER / phase 2. It is specified here for completeness but is explicitly out of scope for the phase-1 implementation.

### Requirement: Host endpoint serves the attendees Markdown
The daemon SHALL expose a host-only endpoint that returns the current `attendees.md` content for the active session, so the host UI can render or download it.

#### Scenario: Host fetches the attendees Markdown
- **WHEN** the host requests the attendees document for the active session
- **THEN** the daemon SHALL return the current `attendees.md` content

#### Scenario: No active session
- **WHEN** the host requests the attendees document while no session is active
- **THEN** the daemon SHALL respond without server error and indicate no attendees document is available

### Requirement: Host can download the attendees sheet as PDF
The host UI SHALL provide a control to render `attendees.md` into a printable PDF client-side, reusing the existing Markdown-to-print rendering pattern (Markdown parsing plus the browser print flow).

#### Scenario: Host renders the attendance PDF
- **WHEN** the host activates the attendance download/print control
- **THEN** the host UI SHALL render the attendees Markdown into a printable PDF layout client-side

#### Scenario: Host can also obtain the raw Markdown
- **WHEN** the host chooses to download the raw attendees file
- **THEN** the host UI SHALL provide the `attendees.md` content as a downloadable Markdown file
