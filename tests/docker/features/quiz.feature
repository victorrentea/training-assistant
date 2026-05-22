Feature: Live Quiz
  As a workshop host, I can create quizzes and participants can vote,
  so that I get real-time audience feedback during sessions.

  Background:
    Given a quiz "Best language?" with options "Python;Java;Go"

  Scenario: Participant sees an open quiz
    Then the participant sees the question and options

  Scenario: Participant votes while quiz is open
    When the participant selects "Java"
    Then the vote is recorded

  Scenario: Closing the quiz shows voters and stops participant vote
    Given the participant selects "Java"
    When the host closes the quiz
    Then the participant cannot vote anymore
    And  the host sees 1 vote for "Java"

  @seq
  Scenario: Marking correct options
    Given the participant selects "Java"
    And the host closes the quiz
    When  the host marks "Java" as correct option
    Then the participant sees "Java" as the correct response
    And the participant is awarded 1000 points
    And the participant's score in host UI is 1000

  Scenario: Slower participant earns fewer points
    Given a participant "Alice" selects "Java" after 1 second
    And  a participant "Bob" selects "Java" after 2 seconds
    And  the host closes the quiz
    When the host marks "Java" as correct option
    Then Alice is awarded 1000 points
    And  Bob is awarded fewer than 1000 points
    And  Alice's score in host UI is greater than Bob's score

  # NOTE: a "Participant changes vote before quiz closes" scenario was originally
  # planned here, but the daemon explicitly rejects re-votes (see
  # daemon/quiz/state.py cast_vote and tests/daemon/test_quiz_state.py
  # `test_cast_vote_single_select_final`). CLAUDE.md's "Votes are mutable"
  # claim is aspirational. Re-add this scenario only after the daemon supports
  # vote replacement.

  Scenario: Wrong answer earns zero points
    Given the participant selects "Python"
    And   the host closes the quiz
    When  the host marks "Java" as correct option
    Then  the participant sees "Java" as the correct response
    And   the participant is awarded 0 points
    And   the participant's score in host UI is 0

  Scenario: Multi-select quiz with partial credit
    Given a multi-select quiz "JVM languages?" with options "Java;Python;Kotlin;Go"
    And   a participant "Alice" selects "Java" and "Kotlin"
    And   a participant "Bob" selects "Java" only
    And   a participant "Carol" selects "Java" and "Go"
    And   a participant "Dan" selects "Go"
    And   the host closes the quiz
    When  the host marks "Java" and "Kotlin" as correct options
    Then  Alice is awarded 1000 points
    And   Bob is awarded fewer points than Alice
    And   Bob's points are greater than 0
    And   Carol is awarded 0 points
    And   Dan is awarded 0 points

  @seq
  Scenario: Score persists after participant refreshes the page
    Given the participant selects "Java"
    And   the host closes the quiz
    And   the host marks "Java" as correct option
    And   the participant is awarded 1000 points
    When  the participant refreshes the page
    Then  the participant's score is still 1000

  @seq
  Scenario: Late joiner can still vote in an open quiz
    Given the quiz is already open
    When  a new participant "Dave" joins the session
    And   a participant "Dave" selects "Java"
    And   the host closes the quiz
    Then  Dave's vote is recorded
    And   the host sees 1 vote for "Java"

  @seq
  Scenario: Host sees live voted-count update as votes arrive
    Given the host sees 0 votes received
    When  a participant "Alice" selects "Java"
    Then  the host sees 1 vote received
    When  a participant "Bob" selects "Python"
    Then  the host sees 2 votes received

  @seq
  Scenario: Participant can vote in next quiz after previous closed by timer
    When the host closes the quiz with a 1 second timer via the slider
    And  the host fires a second quiz "Best framework?" with options "Spring;Quarkus"
    And  the participant selects "Spring"
    Then the vote is recorded
    And  the host sees 1 vote received

  @seq
  Scenario: Host changes the correct option, points re-flow
    Given a participant "Alice" selects "Java"
    And   a participant "Bob" selects "Python"
    And   the host closes the quiz
    And   the host marks "Java" as correct option
    And   Alice is awarded 1000 points
    And   Bob is awarded 0 points
    When  the host marks "Python" as correct option
    Then  Alice is awarded 0 points
    And   Bob is awarded 1000 points
