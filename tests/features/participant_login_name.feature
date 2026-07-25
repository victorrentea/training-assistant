Feature: Participant login and name identity
  As a workshop participant, my first contact with a session is a name gate.
  Entering a real name admits me under that name and records me on the attendance
  sheet; logging in anonymously assigns me a fictional name that is clearly
  tagged as anonymous. A duplicate name is never blocked — only flagged — and the
  daemon never leaks my UUID to other participants.

  # Driven in-process against the REAL daemon participant router (Starlette
  # TestClient) + the REAL participant_state singleton, with the Railway
  # WebSocket publisher captured by a recorder. The attendance sheet is the
  # REAL attendees.md rendered from that same singleton. No browser, no docker.
  #
  # Backend contract behind the frontend "name gate":
  #   POST /api/participant/rejoin   → 200 (recognized ⇒ gate skipped)
  #                                     404 (unknown    ⇒ gate shown)
  #   POST /api/participant/register → join (typed name, or empty body = anonymous)
  #   PUT  /api/participant/name     → rename (never a 409 on a duplicate)

  Background:
    Given a fresh workshop session

  # ── First-visit name gate ──────────────────────────────────────────────────

  Scenario: A brand-new participant is shown the name gate before joining
    When a brand-new participant "u-first" checks whether the session recognizes them
    Then the session does not recognize them
    And no name is committed for "u-first" yet

  # ── Joining with a real name ───────────────────────────────────────────────

  Scenario: Entering a real name admits the participant and lists them on the attendance sheet
    When participant "u-ada" enters the real name "Ada Lovelace"
    Then participant "u-ada" is admitted as "Ada Lovelace"
    And "Ada Lovelace" appears on the attendance sheet
    And "Ada Lovelace" is not tagged anonymous on the attendance sheet

  # ── Logging in anonymously ─────────────────────────────────────────────────

  Scenario: Logging in anonymously ignores typed text and is tagged anonymous
    When participant "u-anon" types "TypedButIgnored" but logs in anonymously
    Then participant "u-anon" is admitted under an auto-assigned fictional name
    And participant "u-anon" is not named "TypedButIgnored"
    And participant "u-anon" is tagged anonymous on the attendance sheet
    And the attendance sheet reports 1 anonymous attendee

  # ── Duplicate names are allowed and flagged, then cleared ──────────────────

  Scenario: A duplicate name is allowed, flagged live, and cleared when one party renames
    Given participant "u1" has joined as "Dana"
    When participant "u2" joins as "Dana"
    Then participant "u2" is admitted without being blocked
    And participant "u2" is flagged with a name conflict
    And the participant-names broadcast lists "Dana" 2 times
    When participant "u2" renames to "Dana-Unique"
    Then no name is duplicated in the participant-names broadcast

  # ── Returning vs. new session ──────────────────────────────────────────────

  Scenario: A returning participant skips the gate, but a new session re-prompts
    Given participant "u-grace" has joined as "Grace Hopper"
    When participant "u-grace" returns to the same session
    Then the session recognizes them as "Grace Hopper"
    When a new session starts
    And participant "u-grace" returns to the same session
    Then the session does not recognize them

  # ── Security: names broadcast is UUID-free ─────────────────────────────────

  Scenario: The participant-names broadcast never contains a UUID
    Given participant "11111111-aaaa-bbbb-cccc-000000000001" has joined as "Alice"
    And participant "22222222-aaaa-bbbb-cccc-000000000002" has joined as "Bob"
    When participant "22222222-aaaa-bbbb-cccc-000000000002" renames to "Carol"
    Then no participant broadcast contains any UUID
    And every participant-names broadcast carries only the names field

  # ── Concurrency ────────────────────────────────────────────────────────────

  Scenario: Two participants entering the same name at once are both admitted and both detect the conflict
    When participants "u1" and "u2" enter the name "Sam" at the same time
    Then both participants are admitted under "Sam"
    And at least one participant detects the name conflict
    And the participant-names broadcast lists "Sam" 2 times

  # ── Name sanitization / injection defense ──────────────────────────────────

  Scenario: A newline in a name cannot inject extra rows into the attendance sheet
    When participant "u-inj" joins with the name "Ada 99. Injected" spanning a newline
    Then the stored name for "u-inj" contains no newline
    And the attendance sheet has exactly one numbered attendee row

  Scenario: Control characters, ANSI escapes and bidi overrides are stripped from a name
    When participant "u-ctl" joins with a name padded with control, ANSI and bidi characters
    Then the stored name for "u-ctl" is "Red Name"
    And the stored name for "u-ctl" has no control, ANSI or bidi characters

  Scenario: An HTML-injection name is stored inert and neutralized on the attendance sheet
    When participant "u-xss" joins with the name "<img src=x onerror=alert(1)>"
    Then the stored name for "u-xss" is kept as literal text
    And the attendance sheet escapes the name so no raw HTML tag survives
