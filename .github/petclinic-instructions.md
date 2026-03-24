---
name: "Pet Clinic Application Instructions"
description: "Self-updating reference guide for working with Pet Clinic application (localhost:4200). Documents discovered features, UI patterns, selectors, and behaviors."
applies_to: "petclinic,pet-clinic,pet clinic,localhost:4200,port 4200"
scope: "workspace"
auto_update: true
---

# Pet Clinic Application — Self-Updating Instructions

**Purpose**: This document serves as the evolving reference guide for working with the Pet Clinic application. Every discovery or learned behavior about the app should be documented here for progressive learning and future task execution.

**Update Policy**: Whenever a new feature, UI pattern, navigation flow, or behavior is discovered while working on Pet Clinic tasks, immediately update the relevant section in this file with the finding.

---

## Quick Reference

- **URL**: http://localhost:4200
- **Status**: Manually explored on 2026-03-25
- **Project Type**: Angular application (based on port 4200 convention)
- **Hosting**: Local development environment

---

## Discovered Functionalities

This section documents features and capabilities discovered during exploration.
**NOTE**: Do not add features here based on assumptions. Only document what has been actively explored and confirmed.

### Main Pages & Navigation
- [x] Landing page → `http://localhost:4200/petclinic/` shows the Petclinic navbar and a welcome page with heading `Welcome to Petclinic`
- [x] Owners search flow → navbar `OWNERS` menu expands to `SEARCH` and `ADD NEW`; `SEARCH` navigates to `http://localhost:4200/petclinic/owners`

### Core Features
- [x] Owner search by last name → Owners page contains a `Last name` textbox plus `Find Owner` button
  - Search example confirmed: entering `Franklin` returns a single matching row for `George Franklin`
  - Result row columns observed: `Name`, `Address`, `City`, `Telephone`, `Pets`
  - Owner names in results are links to owner detail pages such as `/petclinic/owners/1`
- [x] Owner edit flow → from owner detail, `Edit Owner` opens `/petclinic/owners/1/edit`
  - Edit form fields confirmed: `First Name`, `Last Name`, `Address`, `City`, `Telephone`
  - Save action confirmed: changing `City` from `Madison` to `Madison Test` and pressing `Update Owner` returned to `/petclinic/owners/1` showing the updated city value
  - Cleanup confirmed: editing the same owner again and restoring `City` to `Madison` also saved successfully
- [x] Pet lifecycle flow → from `George Franklin`, a pet can be added, edited, and deleted from the owner detail page
  - Add flow confirmed: `Add New Pet` opens `/petclinic/owners/1/pets/add`
  - Add form fields confirmed: readonly owner field, `Name`, `Birth Date`, `Type`, calendar button, `< Back`, `Save Pet`
  - Add example confirmed: creating `Copilot Temp Pet` with birth date `2020-01-02` and type `dog` returned to `/petclinic/owners/1` showing the new pet
  - Edit flow confirmed: first pet-row `Edit Pet` opened `/petclinic/pets/14/edit` for the created pet
  - Edit example confirmed: renaming the pet to `Copilot Temp Pet Updated` and pressing `Update Pet` returned to `/petclinic/owners/1` showing the updated pet name
  - Delete flow confirmed: clicking `Delete Pet` on the created pet removed it immediately from the owner detail page

### Supporting Features
- [x] Owner detail page → clicking `George Franklin` opens `/petclinic/owners/1` with `Owner Information` and `Pets and Visits`
  - Detail actions observed: `Back`, `Edit Owner`, `Add New Pet`, `Edit Pet`, `Delete Pet`, `Add Visit`

---

## UI Patterns & Behaviors

Document consistent patterns discovered in the application.

### Forms & Input
- [x] Form submission patterns → owner search is a simple text input + `Find Owner` button flow on `/petclinic/owners`; owner edit is a multi-field form with `Back` and `Update Owner` buttons on `/petclinic/owners/{id}/edit`
- [x] Pet form submission patterns → add-pet uses `Save Pet`; edit-pet uses `Update Pet`; both return to the owner detail page on successful save
- [ ] Validation feedback display
- [x] Success/error message display → after saving owner or pet edits, no visible success banner/toast was shown; the UI navigated back to the owner detail page and reflected the updated data
- [x] Required vs optional fields → the edit form exposed `First Name`, `Last Name`, `Address`, `City`, and `Telephone` inputs as required in the accessibility tree
- [x] Button states (enabled/disabled) → `Find Owner` was enabled both before typing and after entering `Franklin`; `Save Pet` started disabled on the add form and became enabled after `Name`, `Birth Date`, and `Type` were filled

### Tables & Lists
- [ ] Pagination behavior (if applicable)
- [ ] Sorting options
- [x] Filtering options → results can be filtered by the `Last name` input; confirmed with `Franklin`
- [x] Row selection/actions → clicking an owner name link opens the owner detail page; pet rows expose `Edit Pet`, `Delete Pet`, and `Add Visit`
- [ ] Empty state display

### Navigation Flows
- [x] Menu structure and routing → top navigation contains `HOME`, `OWNERS`, `VETERINARIANS`, `PET TYPES`, `SPECIALTIES`; owner routes observed under `/petclinic/owners` and `/petclinic/owners/{id}`
- [ ] Breadcrumb patterns (if present)
- [x] Back button behavior → both owner detail and owner edit pages expose a visible `Back` button
- [x] Link navigation patterns → owner names in search results are clickable links to owner detail pages; pet actions are button-based on the owner detail page

### Modal/Dialog Patterns
- [x] Confirmation dialogs → deleting the temporary pet from the owner detail page did not show a visible confirmation dialog before removal
- [ ] Edit dialogs
- [x] Delete confirmations → `Delete Pet` removed the pet inline on the owner detail page without an observed toast/banner confirmation

---

## Technical Insights

### Frontend Architecture
- **Framework**: Angular (confirmed by app title `SpringPetclinicAngular` and routed SPA behavior during navigation)
- **CSS Framework**: [To be discovered]
- **State Management**: [To be discovered]
- **Routing**: Client-side routes observed under `/petclinic/welcome`, `/petclinic/owners`, `/petclinic/owners/{id}`, `/petclinic/owners/{id}/pets/add`, `/petclinic/pets/{id}/edit`

### Data Models
- [ ] [To be discovered through exploration]

### API Endpoints
- [ ] Endpoint discovery in progress

---

## Selectors & Element Identification

Document consistent selectors for test automation and interaction.

### Common Button Patterns
```
- `button:has-text("Find Owner")` on `/petclinic/owners`
- `button:has-text("Back")`, `button:has-text("Edit Owner")`, `button:has-text("Add New Pet")` on owner detail pages
- `button:has-text("Update Owner")` on `/petclinic/owners/{id}/edit`
- `button:has-text("Save Pet")` on `/petclinic/owners/{id}/pets/add`
- `button:has-text("Update Pet")`, `button:has-text("Delete Pet")`, `button:has-text("Add Visit")` on pet management flows
```

### Common Input Selectors
```
- Owners search textbox: unlabeled DOM textbox paired with visible label text `Last name` on `/petclinic/owners`
- Owner edit inputs expose accessible names matching visible labels: `First Name`, `Last Name`, `Address`, `City`, `Telephone`
- Add/edit pet inputs expose accessible names including `Name`, `Birth Date`, and `Type`; add-pet also shows readonly owner textbox value `George Franklin`
```

### Navigation Elements
```
- Navbar contains `HOME`, expandable `OWNERS`, expandable `VETERINARIANS`, `PET TYPES`, `SPECIALTIES`
- Owners menu exposes `SEARCH` and `ADD NEW`
```

### Form Patterns
```
- Owner search form = `Last name` textbox + `Find Owner` submit button + results table rendered below on the same page
- Owner edit form = five labeled textboxes (`First Name`, `Last Name`, `Address`, `City`, `Telephone`) + `Back` and `Update Owner`; successful save returns to the owner detail route
- Add-pet form = readonly owner field + `Name` textbox + `Birth Date` textbox/calendar + `Type` dropdown + `< Back` + `Save Pet`; successful save returns to owner detail
- Edit-pet form = owner field + `Name` textbox + `Birth Date` textbox/calendar + pet type shown on form + `Update Pet`; successful save returns to owner detail
```

---

## Known Limitations & Behaviors

- Owner search field is by last name, not full name
- Owner updates are reflected through navigation back to the detail page rather than a visible success notification
- Pet deletion happened immediately from the owner detail page without an observed confirmation dialog

---

## Testing Strategy Notes

- For owner lookup smoke tests, start from `/petclinic/owners`, search `Franklin`, and assert the result link `George Franklin` is shown
- For owner edit smoke tests, open `George Franklin`, change `City`, save with `Update Owner`, assert the detail page reflects the new city, then restore the original value
- For pet lifecycle smoke tests, open `George Franklin`, add a temporary pet, edit its name, verify the updated name appears on the owner detail page, then delete it and assert it no longer appears

---

## Last Updated
- Initial creation: 2026-03-25
- Last modification: 2026-03-25 (owner and pet management flows explored manually)

---

## Discovery Workflow

When exploring new features:

1. **Navigate** to the feature/page
2. **Interact** with UI elements to understand behavior
3. **Document** findings in the appropriate section above
4. **Note** selectors, patterns, and edge cases
5. **Update** the "Last Updated" timestamp

For example:
```markdown
### Pet Management Features
- [x] Viewing pets → List page at /petclinic/pets with table of all pets
  - Selectors: `#pet-table tbody tr` for rows
  - Actions: Click row to view details
  - Sort: Sortable by name, date added (if applicable)
```

---

## Notes for Future Reference

- This document is a living reference
- Discoveries are incremental and cumulative
- Each user request may reveal new functionality
- Cross-reference related features when discovering dependencies

