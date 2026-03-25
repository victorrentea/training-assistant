Feature: Visit Scheduling
  As a clinic receptionist
  I want to log a veterinary visit for a pet
  So that the clinic keeps a complete medical history

  Scenario: Schedule a new visit for an existing pet
    Given I am on the owner detail page for "George Franklin"
    When I click "Add Visit" for pet "Leo"
    Then I am on the add visit page showing pet name "Leo" and owner "George Franklin"
    When I schedule a visit on "2026-04-15" with description "Annual checkup"
    Then I am back on the owner detail page for "George Franklin"
    And pet "Leo" has a visit described as "Annual checkup"

