Feature: Slides Catalog, Viewing, and Follow Mode
  As a workshop host, I present slides and participants follow along,
  so that everyone sees the same content in real time.

  Background:
    Given a fresh session
    And host is connected
    And Alice joins as a participant

  # ── Catalog ──────────────────────────────────────────────────────────

  Scenario: Slides catalog includes topics with last modified timestamps
    Then the slides catalog contains "clean-code" with a last modified timestamp
    And the slides catalog contains "design-patterns" with a last modified timestamp
    And the slides catalog contains "architecture" with a last modified timestamp

  # ── Viewing ──────────────────────────────────────────────────────────

  Scenario: Participant opens a slide and sees rendered content
    When Alice opens slide "clean-code"
    Then Alice sees the slides overlay
    And the slide content is visually rendered
    And Google Drive was called at most 1 time

  Scenario: Second participant gets cached slide with at most 1 Drive call
    Given Bob joins as a participant
    When Alice opens slide "clean-code"
    And Bob opens slide "clean-code"
    Then Bob sees the slides overlay
    And Alice sees the slides overlay
    And Google Drive was called at most 1 time

  Scenario: Navigating back to a slide resumes at the last viewed page
    When Alice opens slide "clean-code"
    And Alice navigates to page 3
    And Alice opens slide "design-patterns"
    And Alice opens slide "clean-code"
    Then Alice sees page 3 of "clean-code"

  Scenario: Participant downloads a slide PDF from the catalog
    When Alice clicks the download button for "clean-code"
    Then Alice receives a valid PDF file

  # ── Slides updated by host ───────────────────────────────────────────

  Scenario: Updated slide shows refreshed timestamp
    When the host updates the slide "clean-code"
    Then the slides catalog contains "clean-code" with last modified timestamp updated

  Scenario: Participant viewing a slide is auto-refreshed when host updates it
    When Alice opens slide "clean-code"
    And the host updates the slide "clean-code"
    Then Alice sees the slides overlay
    And Alice's displayed slide is automatically reloaded

  # ── Follow Mode ──────────────────────────────────────────────────────

  Scenario: Participant follows host's current slide
    Given the addons bridge reports current slide is "Clean Code.pptx" page 3
    When Alice clicks the Follow button
    Then Alice sees the slides overlay
    And the active slide is "clean-code"
    And Alice sees page 3 of "clean-code"

  Scenario: Follower auto-advances when host changes slide
    Given the addons bridge reports current slide is "Clean Code.pptx" page 1
    And Alice clicks the Follow button
    And Alice sees the slides overlay
    When the addons bridge reports current slide is "Design Patterns.pptx" page 2
    Then the active slide is "design-patterns"
    And Alice sees page 2 of "design-patterns"

  @nightly
  Scenario: Follow mode survives slow Google Drive
    Given a 20 second Drive delay on "clean-code"
    And the addons bridge reports current slide is "Clean Code.pptx" page 2
    And a fresh participant joins with follow mode on
    Then the slides overlay opens within 35 seconds
    And the follow button is still enabled
    And the active slide is "clean-code"

  Scenario: Participant sees the updated slide version after host updates it
    When Alice opens slide "clean-code"
    And the slide content is visually rendered
    And the host updates the slide "clean-code"
    And Alice's displayed slide is automatically reloaded
    Then the slide content has changed
