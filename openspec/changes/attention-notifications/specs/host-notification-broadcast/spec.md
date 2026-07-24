## ADDED Requirements

### Requirement: Host can broadcast a notification to all participants
The host page SHALL provide a text input and a "Send" control that, on submit, POSTs the entered text to a host notification endpoint on the daemon. The daemon SHALL broadcast the text to **all** participants as a typed `host_notification` participant message carrying the text and a timestamp. The control SHALL be disabled while the input is empty or whitespace-only.

#### Scenario: Host sends a notification
- **WHEN** the host types a message and activates Send
- **THEN** the daemon SHALL broadcast `{"type":"host_notification","text":"<message>","at":"<iso timestamp>"}` to every connected participant

#### Scenario: Empty message is not sendable
- **WHEN** the notification input is empty or whitespace-only
- **THEN** the Send control SHALL be disabled and no broadcast SHALL be sent

#### Scenario: Broadcast reaches all participants, not a subset
- **WHEN** a host notification is sent while multiple participants are connected
- **THEN** all connected participants SHALL receive the same `host_notification` message

### Requirement: Participant shows an OS notification with sound when permission is granted
When a participant receives a `host_notification` message and OS notification permission is granted, the system SHALL display a native `Notification` carrying the host's text and SHALL produce an audible signal, so the message surfaces even when the session tab is backgrounded.

#### Scenario: Granted permission yields a native notification
- **WHEN** a participant with granted notification permission receives a `host_notification`
- **THEN** the system SHALL show a native OS notification containing the host's text
- **AND** SHALL play a notification sound

#### Scenario: Backgrounded tab still surfaces the notification
- **WHEN** the participant's session tab is backgrounded and a `host_notification` arrives with permission granted
- **THEN** the native OS notification SHALL still appear (the notification's own OS sound is the reliable audible path)

### Requirement: In-page fallback when permission is not granted
When a participant receives a `host_notification` but OS notification permission is not granted, the system SHALL fall back to an in-page toast carrying the host's text together with a best-effort sound, and SHALL NOT fail silently.

#### Scenario: No permission falls back to toast plus sound
- **WHEN** a participant without granted notification permission receives a `host_notification`
- **THEN** the system SHALL show an in-page toast containing the host's text
- **AND** SHALL attempt to play a sound
- **AND** SHALL nudge the participant (via the pinned permission indicator) to enable notifications

### Requirement: Host notification broadcast is refused while the capability is disabled
The daemon SHALL refuse to broadcast a `host_notification` while the attention capability is disabled (`attention_enabled` off), independently of any UI state. Enabling the capability is a precondition for host notifications to reach participants.

#### Scenario: Broadcast refused while disabled
- **WHEN** a host notification is requested while the attention capability is off
- **THEN** the daemon SHALL NOT broadcast any `host_notification` to participants

#### Scenario: Broadcast proceeds once enabled
- **WHEN** a host notification is requested while the attention capability is on
- **THEN** the daemon SHALL broadcast the `host_notification` to all connected participants as specified

### Requirement: Host notification broadcast requires no Railway deploy
The `host_notification` message SHALL be delivered through the existing generic participant `broadcast` relay envelope so that adding it requires no change to the Railway relay/proxy and no Railway redeploy.

#### Scenario: New message type rides the existing envelope
- **WHEN** the daemon broadcasts a `host_notification`
- **THEN** it SHALL be wrapped in the standard `broadcast` envelope and relayed by Railway without any Railway-side code change
