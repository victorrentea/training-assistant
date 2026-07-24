## ADDED Requirements

### Requirement: Daemon sends bell_ring over WS to addons server
When the daemon handles a valid participant bell, it SHALL send a `bell_ring` message over the persistent addons WS connection (`ws://127.0.0.1:8765`) via a new `send_bell(caller_name)` method on the addons bridge client, so the overlay can alert the host. The message SHALL carry the caller's resolved display name.

#### Scenario: Bell sent and card shown
- **WHEN** a participant rings the bell and the addons bridge is connected
- **THEN** the daemon SHALL send `{"type":"bell_ring","caller":"<name>"}` to the addons WS server and the desktop overlay SHALL alert the host

#### Scenario: Addons server not connected — no crash
- **WHEN** the daemon tries to send a bell but the addons WS connection is not active
- **THEN** the daemon SHALL log a warning and continue without raising an error

### Requirement: bell_ring documented in the addons WS protocol
The `bell_ring` message SHALL be documented in `docs/addons-ws.yaml` under the daemon → addons (`subscribe`) direction, alongside `display_emoji`, describing its `type` and `caller` fields.

#### Scenario: Protocol doc lists bell_ring
- **WHEN** the addons WS protocol document is generated or reviewed
- **THEN** it SHALL include a `bell_ring` message with a required `type` (literal `bell_ring`) and a required `caller` string field
