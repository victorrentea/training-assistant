Feature: Owner Management
  As a clinic admin
  I want to register new owners
  So that their pets can be associated to a named client

  Scenario: Create a new owner and verify they appear in the owners list
    Given I am on the add owner page
    When I create owner "Auto" "Tester" at "42 Automation Ave", "Testville", phone "5550000001"
    Then I see "Auto Tester" in the results
    And the result for "Auto Tester" shows city "Testville"
