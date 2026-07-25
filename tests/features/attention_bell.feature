Feature: Attention capability and the participant bell
  The attention capability (bell + host notifications) is an opt-in master switch
  that defaults OFF and resets OFF for every new session. While OFF, both the
  participant bell and the host notification are refused server-side. While ON, a
  ring is forwarded to the overlay and the host under the caller's display name
  (or "Someone" when unknown) — never the caller's UUID — and the per-participant
  rate limit cannot be bypassed with a crafted "__"-prefixed id.

  # Driven in-process against the REAL daemon attention router (host_router +
  # participant_router) and the REAL participant_state singleton. The overlay
  # bridge and host WebSocket are captured with mocks; nothing leaves the process.

  # ── Enable-gate defaults ───────────────────────────────────────────────────

  Scenario: The attention capability defaults OFF and resets OFF for a new session
    Given a brand-new participant state
    Then the attention capability is disabled by default
    When the attention capability is turned on and the session is reset
    Then the attention capability is disabled again

  # ── While OFF: refused server-side ─────────────────────────────────────────

  Scenario: While attention is OFF a bell ring is a server-side no-op
    Given attention is disabled
    And participant "u1" is known as "Alice"
    When participant "u1" rings the bell
    Then the ring is accepted as a no-op
    And nothing is forwarded to the overlay
    And nothing is forwarded to the host

  Scenario: While attention is OFF a host notification is refused
    Given attention is disabled
    When the host broadcasts the notification "Break in 5 min"
    Then the host notification is refused
    And nothing is broadcast to participants

  # ── While ON: forwarded with the caller's name ─────────────────────────────

  Scenario: While attention is ON a ring is forwarded with the caller's name to overlay and host
    Given attention is enabled
    And participant "u1" is known as "Alice"
    When participant "u1" rings the bell
    Then the overlay is notified that "Alice" rang the bell
    And the host is notified that "Alice" rang the bell
    And the host notification carries no UUID

  Scenario: An unknown caller rings as "Someone", never their UUID
    Given attention is enabled
    When unknown participant "u-unknown" rings the bell
    Then the overlay is notified that "Someone" rang the bell

  Scenario: An anonymous participant's ring is flagged anonymous on both sinks
    Given attention is enabled
    And participant "u1" is known as "Gandalf"
    And participant "u1" joined anonymously
    When participant "u1" rings the bell
    Then the overlay ring for "Gandalf" is flagged anonymous
    And the host ring for "Gandalf" is flagged anonymous

  # ── While ON: host can broadcast a notification ────────────────────────────

  Scenario: While attention is ON the host can broadcast a notification within the length cap
    Given attention is enabled
    When the host broadcasts the notification "Break in 5 min"
    Then the host notification is accepted
    And the notification is broadcast to participants

  Scenario: An over-length host notification is rejected and never broadcast
    Given attention is enabled
    When the host broadcasts an over-length notification
    Then the host notification is rejected as invalid
    And nothing is broadcast to participants

  # ── Rate-limit bypass defense ──────────────────────────────────────────────

  Scenario: The bell rate limit cannot be bypassed with a crafted "__"-prefixed id
    Given attention is enabled
    When a crafted "__host__" id rings the bell up to the limit
    Then every ring up to the limit is accepted
    And the next ring is throttled
