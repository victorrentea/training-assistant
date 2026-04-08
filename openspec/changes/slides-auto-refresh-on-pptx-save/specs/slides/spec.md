## MODIFIED Requirements

### Requirement: Participant auto-reloads the active slide when its PDF is freshly updated
When the participant JS receives a `slides_cache_status` WS message and the updated slides list contains a slug whose status just became `cached`, and that slug matches the currently rendered slide deck (the PDF currently displayed in the slide viewer), the participant page SHALL automatically reload the slide iframe/viewer without requiring user interaction.

#### Scenario: Participant is viewing the updated slide deck
- **WHEN** participant receives `slides_cache_status`
- **AND** the participant is currently displaying slide deck with slug `S`
- **AND** the incoming status for slug `S` is `cached` (was previously `stale` or `downloading`)
- **THEN** the participant page SHALL reload the slide viewer for slug `S` automatically

#### Scenario: Participant is viewing a different slide deck
- **WHEN** participant receives `slides_cache_status`
- **AND** the currently displayed slug does not match any freshly-cached slug in the update
- **THEN** the participant page SHALL NOT reload any slide viewer (only refresh the catalog list)

#### Scenario: Participant is not viewing any slide deck
- **WHEN** participant receives `slides_cache_status` and no slide deck is currently displayed
- **THEN** the participant page SHALL only refresh the catalog list (existing behavior)
