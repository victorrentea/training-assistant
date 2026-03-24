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

### Supporting Features
- [x] Owner detail page → clicking `George Franklin` opens `/petclinic/owners/1` with `Owner Information` and `Pets and Visits`
  - Detail actions observed: `Back`, `Edit Owner`, `Add New Pet`, `Edit Pet`, `Delete Pet`, `Add Visit`

---

## UI Patterns & Behaviors

Document consistent patterns discovered in the application.

### Forms & Input
- [x] Form submission patterns → owner search is a simple text input + `Find Owner` button flow on `/petclinic/owners`
- [ ] Validation feedback display
- [ ] Success/error message display
- [ ] Required vs optional fields
- [x] Button states (enabled/disabled) → `Find Owner` was enabled both before typing and after entering `Franklin`

### Tables & Lists
- [ ] Pagination behavior (if applicable)
- [ ] Sorting options
- [x] Filtering options → results can be filtered by the `Last name` input; confirmed with `Franklin`
- [x] Row selection/actions → clicking an owner name link opens the owner detail page
- [ ] Empty state display

### Navigation Flows
- [x] Menu structure and routing → top navigation contains `HOME`, `OWNERS`, `VETERINARIANS`, `PET TYPES`, `SPECIALTIES`; owner routes observed under `/petclinic/owners` and `/petclinic/owners/{id}`
- [ ] Breadcrumb patterns (if present)
- [x] Back button behavior → owner detail page exposes a visible `Back` button
- [x] Link navigation patterns → owner names in search results are clickable links to owner detail pages

### Modal/Dialog Patterns
- [ ] Confirmation dialogs
- [ ] Edit dialogs
- [ ] Delete confirmations

---

## Technical Insights

### Frontend Architecture
- **Framework**: Angular (confirmed by app title `SpringPetclinicAngular` and routed SPA behavior during navigation)
- **CSS Framework**: [To be discovered]
- **State Management**: [To be discovered]
- **Routing**: Client-side routes observed under `/petclinic/welcome`, `/petclinic/owners`, `/petclinic/owners/{id}`

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
```

### Common Input Selectors
```
- Owners search textbox: unlabeled DOM textbox paired with visible label text `Last name` on `/petclinic/owners`
```

### Navigation Elements
```
- Navbar contains `HOME`, expandable `OWNERS`, expandable `VETERINARIANS`, `PET TYPES`, `SPECIALTIES`
- Owners menu exposes `SEARCH` and `ADD NEW`
```

### Form Patterns
```
- Owner search form = `Last name` textbox + `Find Owner` submit button + results table rendered below on the same page
```

---

## Known Limitations & Behaviors

- Owner search field is by last name, not full name
- [To be discovered]

---

## Testing Strategy Notes

- For owner lookup smoke tests, start from `/petclinic/owners`, search `Franklin`, and assert the result link `George Franklin` is shown

---

## Last Updated
- Initial creation: 2026-03-25
- Last modification: 2026-03-25 (owner search flow explored manually)

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

