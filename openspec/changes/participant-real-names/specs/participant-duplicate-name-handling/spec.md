## ADDED Requirements

### Requirement: Duplicate names are permitted and never blocked
The system SHALL allow a participant to register or rename to a name already used by another participant. The server MUST NOT reject a duplicate name with an HTTP 409 (or any hard error) in the `register` or `rename` endpoints. A duplicate is a reported-but-allowed condition, not a failure; the participant SHALL always enter the session.

#### Scenario: Registering with a taken name succeeds
- **WHEN** a participant registers with an explicit name that another participant already uses
- **THEN** the system SHALL accept the registration, store the name, and admit the participant
- **AND** SHALL NOT return an HTTP 409

#### Scenario: Renaming to a taken name succeeds
- **WHEN** a registered participant renames to a name another participant already uses
- **THEN** the system SHALL accept the rename and store the name
- **AND** SHALL NOT return an HTTP 409

### Requirement: Uniqueness is checked only on Enter, server-side
Uniqueness SHALL be checked **only when the participant submits (Enter / rename)**, by the server, comparing the submitted name against current participants. There SHALL be **no live-while-typing duplicate check** and **no "are you sure" confirmation dialog**. The check SHALL only produce a soft flag, never a block.

#### Scenario: No live-typing check before submit
- **WHEN** the participant is typing a name that matches an existing participant but has not submitted
- **THEN** the system SHALL NOT perform a duplicate check and SHALL NOT show a confirmation dialog

#### Scenario: Server checks and flags on Enter
- **WHEN** the participant submits a name
- **THEN** the server SHALL compare it against current participants and return a soft conflict flag while still admitting the participant

### Requirement: Server returns a soft conflict flag on register and rename
On a successful `register` or `rename`, the server SHALL indicate whether the accepted name collided with another participant at write time via a soft, non-blocking `name_conflict` flag on the success response. `register` SHALL return `RegisterResponse{…, name_conflict: bool}` (default `false`); `rename` SHALL return a success response carrying `{name_conflict: bool}`. Neither SHALL return 409.

#### Scenario: Name collided at write time
- **WHEN** the submitted name is used by another participant at the moment the server processes the request
- **THEN** the server SHALL still accept and store the name
- **AND** SHALL return a success response whose `name_conflict` flag is true

#### Scenario: Name is unique at write time
- **WHEN** no other participant is using the submitted name at write time
- **THEN** the server SHALL return a success response whose `name_conflict` flag is false

### Requirement: In-session live duplicate indicator on the participant's own card
While a participant's name duplicates another name in the current participant list, the client SHALL mark **their own** name display (the profile card at the bottom of the session) with all of: a slow red **blink**, a small persistent **underline**, a **⚠️** warning-emoji prefix, the label **"duplicate"**, and a **"click here to change"** affordance. Duplication SHALL be detected by **counting how many times the participant's own name appears in the broadcast name list (≥2 ⇒ duplicate)** — with **no UUID** required.

#### Scenario: Own card shows the duplicate indicator
- **WHEN** the participant's own name appears two or more times in the broadcast participant name list
- **THEN** the client SHALL display, on the participant's own profile card, a slow red blink, a persistent underline, a ⚠️ prefix, the "duplicate" label, and a "click here to change" affordance

#### Scenario: Detection uses no UUID
- **WHEN** the client determines whether its own name is duplicated
- **THEN** it SHALL rely only on the count of its own name in the broadcast names list
- **AND** SHALL NOT require any UUID or per-user id to make that determination

#### Scenario: Click-to-change opens the existing rename editor
- **WHEN** the participant activates the "click here to change" affordance
- **THEN** the client SHALL open the existing crayon name editor so the participant can change their name

### Requirement: Indicator clears for both sides when the name becomes unique
When either the participant or the previously-conflicting participant changes their name so the shared name is no longer duplicated, the server SHALL re-broadcast the updated name list and **both** clients SHALL recompute from it, clearing the indicator wherever the own-name count drops below two.

#### Scenario: Resolving from either side clears both indicators
- **WHEN** one of two participants sharing a name renames to a unique name
- **THEN** the server SHALL re-broadcast the updated name list
- **AND** the indicator SHALL clear on both participants' cards (each recomputes its own count)

### Requirement: Rename UI reuses the existing editor and soft-conflict handling
The existing "change name later" crayon editor SHALL be reused for in-session name changes and SHALL read the soft `name_conflict` flag from the response instead of the prior behavior of silently swallowing a duplicate rejection. It SHALL NOT show a blocking confirmation dialog.

#### Scenario: Changing name later never blocks on duplicate
- **WHEN** a participant edits their name later to one that matches another participant
- **THEN** the client SHALL accept the change, keep the participant admitted, and rely on the in-session indicator rather than a blocking dialog
