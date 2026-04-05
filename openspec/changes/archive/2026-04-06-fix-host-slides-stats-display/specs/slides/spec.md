## MODIFIED Requirements

### Requirement: Current slide tracked via WS push from addons bridge
The daemon SHALL update `slides_current` state when it receives a `slide_changed` message from the addon-bridge. The `slides_current` value SHALL include `presentation_name` and `current_page` so that `slides_log_topic` can be derived from it. The daemon SHALL broadcast `slides_current` to all connected participants and the host immediately upon receiving the event.

#### Scenario: Slide navigation received over WS
- **WHEN** daemon receives `{"type": "slide_changed", "deck": "AI Coding.pptx", "slide": 15}` from the bridge
- **THEN** daemon updates `misc_state.slides_current` to `{presentation_name: "AI Coding.pptx", current_page: 15, ...}` and broadcasts `slides_current` to all participants and host within 100 ms

#### Scenario: PowerPoint closed — slides_current cleared
- **WHEN** daemon receives `{"type": "slide_changed", "deck": null, "slide": null}`
- **THEN** daemon sets `misc_state.slides_current = null` and broadcasts the update

#### Scenario: Bridge not connected — slides_current unchanged
- **WHEN** the addon-bridge WS client is disconnected
- **THEN** daemon retains the last known `slides_current` value (no reset, no file-poll fallback)
