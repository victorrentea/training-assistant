## ADDED Requirements

### Requirement: Pinned always-visible notification-permission indicator
The participant page SHALL present a fixed, always-visible element that reflects the current OS notification-permission state (granted, not-granted, or denied). The element SHALL remain visible across participant views (mirroring the fixed placement of the reconnect banner or the floating-reactions stack).

#### Scenario: Indicator reflects granted state
- **WHEN** OS notification permission is already granted
- **THEN** the pinned indicator SHALL show a granted state and SHALL NOT prompt for permission

#### Scenario: Indicator reflects not-granted state
- **WHEN** OS notification permission has not yet been requested or is not granted
- **THEN** the pinned indicator SHALL show a not-granted state inviting the participant to enable notifications

### Requirement: The permission affordance is presented only while the capability is enabled
The pinned indicator and its `Notification.requestPermission()` affordance SHALL be presented/active only while the attention capability is enabled (`attention_enabled` on). While the capability is disabled the indicator SHALL be hidden/inactive and SHALL NOT prompt for OS-notification permission, since the host is not using notifications. It SHALL appear or disappear live when the host toggles the capability.

#### Scenario: Indicator hidden while capability disabled
- **WHEN** the attention capability is off
- **THEN** the pinned permission indicator SHALL be hidden/inactive and SHALL NOT prompt for permission

#### Scenario: Indicator activates live when the host enables the capability
- **WHEN** the host enables the attention capability while a participant is connected
- **THEN** the pinned permission indicator SHALL appear/activate on that participant's page without a reload

### Requirement: Permission is requested only on a user gesture
The system SHALL call `Notification.requestPermission()` **only** from within the pinned indicator's click handler (a user gesture) and SHALL NOT call it on page load.

#### Scenario: Clicking the indicator requests permission
- **WHEN** the participant clicks the pinned indicator while permission is not granted
- **THEN** the system SHALL call `Notification.requestPermission()` and update the indicator to reflect the result

#### Scenario: No permission prompt on load
- **WHEN** the participant page loads
- **THEN** the system SHALL NOT call `Notification.requestPermission()` automatically

#### Scenario: Denied permission is explained, not re-prompted blindly
- **WHEN** notification permission is `denied`
- **THEN** the pinned indicator SHALL explain that notifications must be re-enabled in the browser settings, rather than relying on a repeat prompt (which the browser ignores once denied)

### Requirement: Audio is unlocked during the permission-grant gesture
During the same user-gesture click that requests permission, the system SHALL unlock an `<audio>` element (play then immediately pause a short/muted clip) so later notification sounds are more likely to play, including from a backgrounded tab.

#### Scenario: Grant gesture blesses the audio element
- **WHEN** the participant clicks the pinned indicator to enable notifications
- **THEN** the system SHALL unlock an `<audio>` element within that gesture so a subsequent sound can be played from a WS-message handler
