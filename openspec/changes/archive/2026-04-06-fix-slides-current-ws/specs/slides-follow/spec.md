## ADDED Requirements

### Requirement: slides_current WS message carries non-null payload
When the host changes slide, the `slides_current` WebSocket message sent to participants SHALL contain a non-null dict with at least `current_page`, `presentation_name`, and `url` fields.

#### Scenario: Host advances to slide 63
- **WHEN** the daemon receives `{"type": "slide", "deck": "AI Coding.pptx", "slide": 63}` from the addon bridge
- **THEN** participants receive `{"type": "slides_current", "slides_current": {"current_page": 63, "presentation_name": "AI Coding.pptx", ...}}` with a non-null `slides_current` value

#### Scenario: No active deck
- **WHEN** the daemon has no matching deck for the received slide event
- **THEN** participants receive `{"type": "slides_current", "slides_current": null}` (existing clear behavior unchanged)
