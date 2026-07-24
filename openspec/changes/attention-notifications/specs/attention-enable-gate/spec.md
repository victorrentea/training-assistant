## ADDED Requirements

### Requirement: The attention capability is disabled by default and reset off at every session start
The whole attention capability — **both** directions (host→participant OS notifications and participant→host bell) — SHALL be governed by a single session-wide flag `attention_enabled` on `participant_state`. The flag SHALL default to OFF (disabled) and SHALL be re-initialised to OFF whenever participant state is reset for a fresh session, so no session ever starts with the bell or notification surface exposed. This mirrors the existing `emoji_global_enabled` master switch, except that its default is OFF rather than ON.

#### Scenario: Fresh state starts disabled
- **WHEN** participant state is first constructed
- **THEN** `attention_enabled` SHALL be OFF (`False`)

#### Scenario: Session reset returns the gate to off
- **WHEN** participant state is reset at the start of a new session
- **THEN** `attention_enabled` SHALL be set back to OFF, regardless of its previous value

#### Scenario: Gate is persisted and restored
- **WHEN** participant state is snapshotted and later restored
- **THEN** `attention_enabled` SHALL be carried through the snapshot and restore, and a restore that omits the flag SHALL leave it at its safe default of OFF

### Requirement: Host enables or disables the whole capability from the host UI
The host page SHALL provide a master toggle control (a badge mirroring the existing emoji master badge) that turns the attention capability on or off. Activating it SHALL POST to a host toggle endpoint on the daemon that flips `attention_enabled`, persists it, and returns the new state. The host control SHALL reflect the current on/off state.

#### Scenario: Host turns the capability on
- **WHEN** the host activates the master toggle while the capability is off
- **THEN** the daemon SHALL set `attention_enabled` to ON, persist it, and return the new state, and the host control SHALL reflect the ON state

#### Scenario: Host turns the capability off
- **WHEN** the host activates the master toggle while the capability is on
- **THEN** the daemon SHALL set `attention_enabled` to OFF, persist it, and return the new state, and the host control SHALL reflect the OFF state

### Requirement: The gate state is broadcast live to participants and carried in participant state
When the host flips the flag, the daemon SHALL broadcast a typed `attention_enabled` participant message so every connected participant updates immediately without reloading. The flag SHALL also be included in the per-participant state payload returned on page load and WS reconnect, so a participant joining or reconnecting renders the correct surface.

#### Scenario: Toggling broadcasts to all participants live
- **WHEN** the host toggles the capability
- **THEN** the daemon SHALL broadcast `{"type":"attention_enabled","enabled":<bool>}` to every connected participant
- **AND** each participant SHALL show or hide the bell button and the notification-permission indicator accordingly, without reloading the page

#### Scenario: Joining participant learns the current gate state
- **WHEN** a participant loads the page or reconnects while the capability is already on
- **THEN** the participant state payload SHALL report `attention_enabled` as ON and the participant SHALL render the bell button and permission affordance

#### Scenario: Joining participant sees nothing while disabled
- **WHEN** a participant loads the page or reconnects while the capability is off
- **THEN** the participant state payload SHALL report `attention_enabled` as OFF and the participant SHALL NOT render the bell button or the permission affordance

### Requirement: The daemon enforces the gate independently of the UI (defense in depth)
Hiding controls in the UI SHALL NOT be the only enforcement. The daemon SHALL independently reject attention traffic while `attention_enabled` is off: the participant bell endpoint SHALL reject/ignore a ring, and the host→participant notification broadcast SHALL be refused. A client that calls these endpoints directly while the capability is disabled SHALL achieve nothing.

#### Scenario: Direct bell call is ignored while disabled
- **WHEN** a `POST` to the participant bell endpoint arrives while `attention_enabled` is off
- **THEN** the daemon SHALL NOT forward anything to the overlay, SHALL NOT notify the host, and SHALL treat the ring as a no-op

#### Scenario: Host notification broadcast is refused while disabled
- **WHEN** a host notification broadcast is requested while `attention_enabled` is off
- **THEN** the daemon SHALL NOT broadcast any `host_notification` to participants

#### Scenario: Traffic flows once enabled
- **WHEN** the capability is on
- **THEN** the bell endpoint and the host notification endpoint SHALL process requests normally

### Requirement: The Swift overlay requires no change for the gate
The macOS overlay side (the already-merged `victor-macos-addons` `bell-overlay-card`) SHALL require no modification for this gate. Because the daemon never emits `bell_ring` while `attention_enabled` is off, the overlay is inherently inert when the capability is disabled, and no work in the addons repository is needed for the enable-gate.

#### Scenario: Overlay stays inert while disabled without any addons change
- **WHEN** the capability is off and participants exist
- **THEN** the daemon SHALL never send `bell_ring`, so the overlay shows nothing — with no change required to the overlay code
