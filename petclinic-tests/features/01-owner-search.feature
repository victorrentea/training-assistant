Feature: Owner Search
  As a clinic receptionist
  I want to search owners by last name
  So I can quickly locate an existing client

  Scenario: Find an existing owner by last name
    Given I am on the owners search page
    When I search for last name "Franklin"
    Then I see "George Franklin" in the results
    And the result for "George Franklin" shows city "Madison"

  Scenario: Search returns no results for an unknown name
    Given I am on the owners search page
    When I search for last name "Nonexistent99"
    Then I see no owners in the results

