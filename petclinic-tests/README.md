# PetClinic Playwright BDD Tests

End-to-end test suite for [Spring PetClinic Angular](https://github.com/spring-petclinic/spring-petclinic-angular) using [playwright-bdd](https://github.com/vitalets/playwright-bdd) (v7). Tests are written in plain Gherkin and cover the five most critical user flows in the application: owner search, owner management, pet lifecycle, visit scheduling, and veterinarian management.

---

## Prerequisites

| Requirement | Version |
|---|---|
| Node.js | 18 or later |
| Spring PetClinic Angular | running at `http://localhost:4200` |

> The Angular frontend must be running against a PetClinic REST backend before executing any tests.

---

## Install & First Run

```bash
# 1. Install dependencies
npm install

# 2. Install Playwright browsers (first time only)
npx playwright install --with-deps chromium

# 3. Run all tests (headless)
npm test
```

`npm test` runs `bddgen` (generates `.features-gen/` from `.feature` files) then `playwright test`.

---

## Running Specific Tests

```bash
# Run a single feature file
npx playwright test --grep "Owner Search"

# Run headed (visible browser window)
npm run test:headed

# Interactive Playwright UI (great for debugging)
npm run test:ui

# View the HTML report from the last run
npm run report
```

---

## Project Structure

| Path | Purpose |
|---|---|
| `features/` | Gherkin `.feature` files — the human-readable test specifications |
| `features/01-owner-search.feature` | Search owners by last name |
| `features/02-owner-management.feature` | Create a new owner |
| `features/03-pet-lifecycle.feature` | Add, rename, and delete a pet |
| `features/04-visit-scheduling.feature` | Schedule a vet visit for a pet |
| `features/05-veterinarians.feature` | View, add, and delete veterinarians |
| `pages/` | Page Object Models — encapsulate all browser interactions |
| `pages/NavigationPage.ts` | Base class: nav menu helpers and `goto()` |
| `pages/OwnersSearchPage.ts` | `/owners` — search form and results table |
| `pages/OwnerDetailPage.ts` | `/owners/:id` — owner info, pets, and visits |
| `pages/OwnerFormPage.ts` | `/owners/add` and `/owners/:id/edit` |
| `pages/PetFormPage.ts` | Add/edit pet forms |
| `pages/VisitFormPage.ts` | Add visit form |
| `pages/VetsPage.ts` | `/vets` — list, add, and delete vets |
| `steps/fixtures.ts` | Wires all page objects as Playwright fixtures; defines `OwnerCleanup` |
| `steps/owner.steps.ts` | Owner search and CRUD step implementations |
| `steps/pet.steps.ts` | Pet lifecycle step implementations |
| `steps/visit.steps.ts` | Visit scheduling step implementations |
| `steps/vet.steps.ts` | Veterinarian step implementations |
| `.features-gen/` | Auto-generated Playwright spec files — **do not edit** |
| `playwright.config.ts` | Playwright + BDD configuration (base URL, reporters, timeouts) |

---

## Adding New Tests

1. **Write a `.feature` file** in `features/` using Gherkin (`Given / When / Then`).
2. **Regenerate specs**: `npm run bddgen` — it will print any unimplemented steps.
3. **Implement missing steps** in the appropriate `steps/*.steps.ts` file. If a new page is needed, add a Page Object in `pages/` extending `NavigationPage`, then wire it as a fixture in `steps/fixtures.ts`.

---

## Test Data Isolation

The `ownerCleanup` fixture (defined in `steps/fixtures.ts`) tracks owners created during a test run and deletes them via the PetClinic REST API (`DELETE /petclinic/api/owners/{id}`) in teardown — even when a test fails. Step definitions that create owners call `ownerCleanup.track(lastName)` to register the owner for removal. No manual database cleanup is required between runs.

