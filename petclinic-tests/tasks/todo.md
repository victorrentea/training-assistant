# Petclinic Playwright BDD Framework — Completion Plan

## Context
The previous agent built a solid foundation: 5 Gherkin feature files, 7 Page Object Models,
step definitions, and fixture wiring. BDD generation compiles cleanly. The following tasks
complete and harden what was left behind.

---

## Tasks

- [x] **1. Audit existing framework** — verify all 5 features, pages, steps exist and compile
  - ✅ 5 feature files covering Owner Search, Owner CRUD, Pet Lifecycle, Visit Scheduling, Vets
  - ✅ 7 Page Objects: NavigationPage, OwnersSearchPage, OwnerDetailPage, OwnerFormPage, PetFormPage, VisitFormPage, VetsPage
  - ✅ Step files: owner.steps.ts, pet.steps.ts, visit.steps.ts, vet.steps.ts
  - ✅ fixtures.ts wiring all page objects
  - ✅ BDD generates .spec.js files without errors
  - ⚠️ `importTestFrom` deprecation warning in playwright.config.ts
  - ⚠️ `clickEditOwner()` in OwnerDetailPage.ts incomplete (no wait after click)
  - ⚠️ No README.md for framework usage
  - ⚠️ Test-02 creates "Auto Tester" owner accumulating data across runs
  - ⚠️ Test-04 adds a visit that accumulates across runs

- [x] **2. Fix `importTestFrom` deprecation warning** in `playwright.config.ts`
  - Removed `importTestFrom`; fixtures.ts added explicitly to `steps` array glob

- [x] **3. Fix test-02 data isolation** — after owner creation redirect, search explicitly before asserting
  - `When I create owner` step now calls `ownersSearchPage.searchByLastName(lastName)` after redirect
  - `OwnerCleanup` class added to `steps/fixtures.ts`; wired as `ownerCleanup` fixture with teardown
  - Step calls `ownerCleanup.track(lastName)` to register the owner for REST API deletion

- [x] **4. Complete `clickEditOwner()` in OwnerDetailPage.ts** — added `waitForURL(/\/owners\/\d+\/edit$/)` after click

- [x] **5. Add `README.md`** documenting framework structure, how to install, and how to run

- [x] **6. Final TypeScript compilation pass** — `npx tsc --noEmit` exits 0; `bddgen` exits 0

---

## Execution Strategy
Tasks 2, 4, 6: trivial — done inline.
Tasks 3, 5: one sub-agent each to keep context clean.

