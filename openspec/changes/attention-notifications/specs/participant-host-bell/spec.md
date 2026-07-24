## ADDED Requirements

### Requirement: Participant bell button in the reaction bar
The participant page SHALL provide a bell button in the reaction-bar container (`#emoji-main-bar`), wired like the emoji buttons. Activating it SHALL call a `ringBell()` function that POSTs to `/{sessionId}/api/participant/bell` with the `X-Participant-ID` header and no request body.

#### Scenario: Ringing the bell posts to the bell endpoint
- **WHEN** the participant taps the bell button
- **THEN** the system SHALL `POST /{sessionId}/api/participant/bell` with header `X-Participant-ID` set to the participant's UUID and an empty body

#### Scenario: Client-side throttle limits rapid rings
- **WHEN** the participant taps the bell repeatedly in quick succession
- **THEN** the client SHALL throttle the rings (mirroring the emoji throttle) and SHALL surface a gentle "slow down" hint when the server responds with a rate-limit status

### Requirement: The bell surface and endpoint are gated by the master enable-gate
The bell button SHALL be present in the reaction bar only while the attention capability is enabled (`attention_enabled` on), and SHALL appear or disappear live when the host toggles the capability. Independently of the UI, the daemon bell endpoint SHALL reject/ignore a ring while the capability is disabled — before resolving the caller, logging, forwarding to the overlay, or notifying the host — so a direct call achieves nothing.

#### Scenario: Bell button hidden while disabled
- **WHEN** the attention capability is off
- **THEN** the participant reaction bar SHALL NOT show the bell button

#### Scenario: Bell button appears live when the host enables the capability
- **WHEN** the host enables the attention capability while a participant is connected
- **THEN** the bell button SHALL appear in that participant's reaction bar without a page reload

#### Scenario: Bell endpoint rejects a ring while disabled
- **WHEN** a bell POST arrives while the capability is off
- **THEN** the daemon SHALL treat it as a no-op — it SHALL NOT forward `bell_ring` to the overlay nor notify the host

### Requirement: Daemon bell endpoint resolves the caller and logs who and when
The daemon SHALL expose `POST /api/participant/bell` (router `daemon/bell/router.py`, mounted next to the emoji routers). The handler SHALL resolve the caller's display name from the `X-Participant-ID` header via `participant_state.participant_names` and SHALL log who rang and when, reusing the daemon `addons`-channel logging idiom (the timestamp is auto-prefixed by the daemon logger).

#### Scenario: Bell resolves the participant's name
- **WHEN** a bell POST arrives with a known `X-Participant-ID`
- **THEN** the daemon SHALL resolve the caller name via `participant_state.participant_names.get(pid, pid)`

#### Scenario: Bell is logged with the caller name
- **WHEN** the daemon handles a bell
- **THEN** it SHALL emit a daemon log line on the `addons` channel identifying the caller (e.g. `🔔 '<name>' rang the bell`)

#### Scenario: Missing participant id is rejected
- **WHEN** a bell POST arrives without an `X-Participant-ID` header
- **THEN** the daemon SHALL respond with a 400 error and SHALL NOT forward anything to the overlay

#### Scenario: Server-side rate limit protects the host
- **WHEN** a single participant rings far more often than the allowed rate
- **THEN** the daemon SHALL reject the excess rings with a rate-limit status and SHALL NOT forward them to the overlay

### Requirement: Daemon forwards the bell to the overlay via the addons bridge
On a valid bell, the daemon SHALL forward it to the macOS overlay by calling `send_bell(caller_name)` on the addons bridge client, emitting the shared `bell_ring` message on `ws://127.0.0.1:8765`. The forward SHALL be best-effort: if the bridge is disconnected the daemon SHALL log the drop and still return success to the participant.

#### Scenario: Bell forwarded when the overlay is connected
- **WHEN** the addons bridge is connected and a valid bell arrives
- **THEN** the daemon SHALL send `{"type":"bell_ring","caller":"<name>"}` over the bridge

#### Scenario: Overlay disconnected does not error the participant
- **WHEN** the addons bridge is not connected and a bell arrives
- **THEN** the daemon SHALL log that the bell could not be forwarded and SHALL still return a success response to the participant

### Requirement: Bell may also render on the host browser page
Host-browser rendering of an incoming bell is optional (mirroring the emoji dual-render design). When it is enabled, the daemon SHALL notify the host browser of a valid bell so the host page can surface it in addition to the overlay card.

#### Scenario: Host page receives the bell when dual-render is enabled
- **WHEN** host-browser rendering is enabled, a valid bell is handled, and the host browser is connected
- **THEN** the daemon SHALL send a host-directed message identifying the caller so the host page can render it

#### Scenario: Overlay card alone is sufficient when dual-render is disabled
- **WHEN** host-browser rendering is not enabled and a valid bell is handled
- **THEN** the daemon SHALL forward the bell to the overlay only and the host page rendering SHALL be omitted
