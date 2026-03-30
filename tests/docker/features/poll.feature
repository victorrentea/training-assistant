Feature: Live Poll
  As a workshop host, I can create polls and participants can vote,
  so that I get real-time audience feedback during sessions.

  Background:
    Given a fresh session
    And a host and participant are connected

  Scenario: Full poll lifecycle
    When the host creates a poll "Best language?" with options "Python,Java,Go"
    Then the participant sees poll question "Best language?"
    And the participant sees 3 options
    When the participant votes for "Python"
    And the host closes the poll
    Then the participant sees the closed banner
    And the participant sees percentages

  Scenario: Correct answer scoring
    When the host creates a poll "Capital of France?" with options "Paris,London,Berlin"
    And the participant votes for "Paris"
    And the host closes the poll
    And the host marks "Paris" as correct
    Then the participant score is at least 100

  Scenario: Zero votes show 0%
    When the host creates a poll "Nobody votes?" with options "A,B,C"
    And the host closes the poll
    Then all percentages are 0
