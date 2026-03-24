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
- **Status**: [To be tested by user - currently untested]
- **Project Type**: Angular application (based on port 4200 convention)
- **Hosting**: Local development environment

---

## Discovered Functionalities

This section documents features and capabilities discovered during exploration.
**NOTE**: Do not add features here based on assumptions. Only document what has been actively explored and confirmed.

### Main Pages & Navigation
- [ ] 

### Core Features
- [ ] 

### Supporting Features
- [ ]

---

## UI Patterns & Behaviors

Document consistent patterns discovered in the application.

### Forms & Input
- [ ] Form submission patterns
- [ ] Validation feedback display
- [ ] Success/error message display
- [ ] Required vs optional fields
- [ ] Button states (enabled/disabled)

### Tables & Lists
- [ ] Pagination behavior (if applicable)
- [ ] Sorting options
- [ ] Filtering options
- [ ] Row selection/actions
- [ ] Empty state display

### Navigation Flows
- [ ] Menu structure and routing
- [ ] Breadcrumb patterns (if present)
- [ ] Back button behavior
- [ ] Link navigation patterns

### Modal/Dialog Patterns
- [ ] Confirmation dialogs
- [ ] Edit dialogs
- [ ] Delete confirmations

---

## Technical Insights

### Frontend Architecture
- **Framework**: [To be discovered]
- **CSS Framework**: [To be discovered]
- **State Management**: [To be discovered]
- **Routing**: [To be discovered]

### Data Models
- [ ] [To be discovered through exploration]

### API Endpoints
- [ ] Endpoint discovery in progress

---

## Selectors & Element Identification

Document consistent selectors for test automation and interaction.

### Common Button Patterns
```
- [To be discovered]
```

### Common Input Selectors
```
- [To be discovered]
```

### Navigation Elements
```
- [To be discovered]
```

### Form Patterns
```
- [To be discovered]
```

---

## Known Limitations & Behaviors

- [To be discovered]
- [To be discovered]

---

## Testing Strategy Notes

- [To be discovered]

---

## Last Updated
- Initial creation: 2026-03-25
- Last modification: 2026-03-25

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

