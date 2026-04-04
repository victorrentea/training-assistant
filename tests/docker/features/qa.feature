Feature: Q&A with Upvoting
  Participants submit questions via WebSocket, others can upvote,
  and the host sees a ranked list of questions.

  Background:
    Given a fresh session

  Scenario: Submit question and host sees it
    Given the host has opened the Q&A tab
    And a participant joins as "Alice"
    When the participant submits question "What is dependency injection?"
    Then the host sees a question containing "dependency injection"
    And the question has 0 upvotes

  Scenario: Upvoting and sort order
    Given the host has opened the Q&A tab
    And 3 participants have joined
    When participant 1 submits question "Q-Alpha"
    And participant 1 submits question "Q-Beta"
    And participant 1 submits question "Q-Gamma"
    And participant 2 upvotes the question containing "Alpha"
    And participant 2 upvotes the question containing "Beta"
    And participant 3 upvotes the question containing "Alpha"
    Then question "Alpha" has 2 upvotes
    And question "Beta" has 1 upvotes
    And question "Gamma" has 0 upvotes
    And questions are sorted by upvotes descending

  Scenario: Late joiner sees existing Q&A
    Given the host has opened the Q&A tab
    And a participant joins as "EarlyBird"
    When the participant submits question "Earlier question"
    And a new participant joins the session
    Then the new participant sees question "Earlier question"
