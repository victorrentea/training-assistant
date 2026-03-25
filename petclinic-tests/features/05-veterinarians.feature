Feature: Veterinarian Management
  As a clinic admin
  I want to view and maintain the list of veterinarians
  So that the clinic directory is always up to date

  Scenario: View existing veterinarians and their specialties
    Given I am on the veterinarians list page
    Then the list contains 6 veterinarians
    And vet "Helen Leary" has specialty "radiology"
    And vet "Linda Douglas" has specialties "surgery" and "dentistry"
    And vet "James Carter" has no specialties listed

  Scenario: Add a new veterinarian and then remove them
    Given I navigate to add a new veterinarian
    When I create vet "Test" "Doctor"
    Then "Test Doctor" appears in the veterinarians list
    When I delete vet "Test Doctor"
    Then "Test Doctor" no longer appears in the veterinarians list

