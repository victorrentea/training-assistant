Feature: Pet Lifecycle
  As a clinic receptionist
  I want to add, update, and remove pets from an owner's record
  So that the clinic always has accurate pet information

  Scenario: Add, rename, and delete a pet — leaves no trace
    Given I am on the owner detail page for "George Franklin"
    When I add a new pet with name "GherkinDog", birth date "2020-06-15", type "dog"
    Then pet "GherkinDog" appears in the pets section
    When I rename pet "GherkinDog" to "GherkinDogRenamed"
    Then pet "GherkinDogRenamed" appears in the pets section
    When I delete pet "GherkinDogRenamed"
    Then pet "GherkinDogRenamed" is no longer in the pets section

