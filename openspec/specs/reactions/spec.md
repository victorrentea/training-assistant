### Requirement: Emoji reactions reach the desktop overlay
The daemon SHALL forward each participant emoji reaction to the desktop overlay running on the trainer's Mac via the persistent addon-bridge WebSocket connection. If the bridge is not connected, the daemon SHALL skip the overlay forward silently (best-effort). The reaction SHALL still be forwarded to the host browser regardless of bridge state.

#### Scenario: Bridge connected — emoji animates on overlay
- **WHEN** a participant posts an emoji reaction and the addon-bridge WS client is connected
- **THEN** daemon sends `{"type": "emoji_reaction", "emoji": "<emoji>"}` over the bridge WS; bridge triggers the overlay animation

#### Scenario: Bridge not connected — no error
- **WHEN** a participant posts an emoji reaction and the addon-bridge WS client is not connected
- **THEN** daemon logs at debug level and skips the bridge send; participant receives `{ok: true}` normally; host browser still receives the reaction
