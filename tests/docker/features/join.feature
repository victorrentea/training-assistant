Feature: Participant Joining a Session
  As a workshop participant, I join a session by entering a code and choosing a name,
  so that I can interact with the host and other participants in real time.

  Background:
    Given a session with code "ABCDEF" is active on Daemon

  # ── Session Code Entry ───────────────────────────────────────────────

  Scenario: Valid 6-digit code redirects to participant page
    When Alice opens "/"
    And Alice enters the session code of the active session
    Then Alice sees the participant page

  Scenario: Invalid session code shakes the input and shows error
    When Alice enters an invalid session code "XXXXXX"
    Then Alice sees a toaster "Invalid session code"

  # ── Name Entry ───────────────────────────────────────────────────────

  Scenario: New participant sees name input after entering session code
    When Alice navigates to the participant page
    Then Alice sees the name input screen
    And the Join button is disabled

  Scenario: Participant joins with a custom name
    When Alice navigates to the participant page
    And Alice enters the name "Alice"
    And Alice clicks Join
    Then Alice enters the app
    And Alice's display name is "Alice"

  Scenario: Participant joins with a random name
    When Alice navigates to the participant page
    And Alice clicks the Random Name button
    Then Alice enters the app
    And Alice has a server-assigned display name

  Scenario: Duplicate name is rejected with shake and toaster
    Given Alice joins as a participant
    When Bob navigates to the participant page
    And Bob enters the name "Alice"
    And Bob clicks Join
    Then the name input shakes
    And Bob sees a toaster "Name already taken"
    And Bob is still on the name input screen

  Scenario: Join button is disabled when name input is empty
    When Alice navigates to the participant page
    Then the Join button is disabled
    When Alice enters the name "  "
    Then the Join button is disabled

  # ── Rejoin ──────────────────────────────────────────────────────────

  Scenario: Returning participant's name is restored after session restart
    Given Alice joins as a participant with name "Alice"
    And the host ends the session
    And the host resumes the session
    When Alice opens "/{session_id}/"
    Then Alice enters the app
    And Alice's display name is "Alice"

  # ── Routing Matrix ──────────────────────────────────────────────────

  Scenario Outline: Visitor opens <url> with daemon=<daemon>, uuid=<uuid> → <redirect> showing <expected>
    Given the daemon state is "<daemon>"
    And Alice's stored UUID is "<uuid>"
    When Alice opens "<url>"
    Then Alice is on "<redirect>"
    And Alice sees "<expected>"

    Examples:
      | url     | daemon | uuid          | redirect | expected              |
      # Landing page — daemon/session states
      | /       | OFF    | none          | /        | "Host not connected"  |
      | /       |        | none          | /        | "No session started"  |
      | /       | AAAAAA | none          | /        | session code input    |
      # Direct link — session validation
      | /AAAAAA | OFF    | none          | /        | "Host not connected"  |
      | /AAAAAA | AAAAAA | none          | /AAAAAA/ | name input            |
      | /XXXXXX | AAAAAA | none          | /XXXXXX/ | "Session not started" |
      # Returning participant — UUID resolution
      | /AAAAAA | AAAAAA | same_session  | /AAAAAA/ | app (rejoined)        |
      | /AAAAAA | AAAAAA | other_session | /AAAAAA/ | name input            |
