Feature: Session hijack protection
  A stale, old or unknown session link must never steer a participant onto the
  currently-active session — that would leak one cohort into another. Every such
  request lands on the neutral "/?error=invalid" page, and a session switch drops
  the previous cohort rather than redirecting it onto the new session.

  # Driven in-process against the REAL railway.app ASGI app (Starlette
  # TestClient for HTTP + WebSocket) and the REAL ws-router session handlers.
  # No docker, no live daemon.

  Background:
    Given a clean gateway with rate limiting disabled

  # ── Stale link on the page route ───────────────────────────────────────────

  Scenario: A stale session page link lands on the neutral error page
    Given the active session is "newsess"
    When a browser opens the stale session page "/oldsess/"
    Then it is redirected to "/?error=invalid"
    And it is never redirected onto the active session "newsess"

  Scenario: An unknown session API probe is rejected, not resolved to the active session
    Given the active session is "newsess"
    When a browser probes the unknown session status "/zzzzzz/api/status"
    Then the gateway responds 404
    And the response does not expose the active session "newsess"

  # ── Stale link on the WebSocket route ──────────────────────────────────────

  Scenario: A stale session WebSocket is steered to the neutral error page
    Given the active session is "newsess"
    When a participant connects to the stale session socket "/ws/oldsess/pax-uuid"
    Then the socket receives a redirect to "/?error=invalid"
    And the socket redirect does not mention the active session "newsess"

  # ── Session switch does not steer the old cohort onto the new session ───────

  Scenario: Switching the active session drops the old cohort instead of steering it onto the new session
    Given the active session is "old111" with a connected participant and host
    When the daemon switches the active session to "new222"
    Then the old participant is steered to the neutral error page
    And the old participant is never steered onto "new222" nor "old111"
    And the old participant socket is closed
    And the old cohort's cached state is cleared

  Scenario: Ending the session steers the old cohort to the neutral error page
    Given the active session is "old111" with a connected participant and host
    When the daemon ends the active session
    Then the old participant is steered to the neutral error page
    And the active session is cleared
