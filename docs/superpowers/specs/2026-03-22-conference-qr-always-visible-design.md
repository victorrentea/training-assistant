# Conference Mode: QR Code Always Visible in Left Panel

## Problem

In conference mode, the `conference-qr` container (QR code + URL + participant count) in the left column is only shown when an activity is active. Additionally, tab content (especially Code Review) can overflow and obscure the QR area. The QR should be permanently visible so conference attendees can join at any time.

## Design

In conference mode, the left column (`host-col-left`) splits into a CSS grid with two equal rows:

1. **Top half (1fr)**: Tab bar + tab content area with internal scroll (`overflow-y: auto`)
2. **Bottom half (1fr)**: `conference-qr` container, always visible

### CSS Changes (host.css)

Add a class or conference-mode rule for `.host-col-left`:
- `display: grid; grid-template-rows: 1fr 1fr`
- Tab content wrapper gets `overflow-y: auto; min-height: 0` to scroll within its half
- `conference-qr` takes the bottom half with `display: flex` (already styled)

### JS Changes (host.js)

- `applyConferenceLayout(true)`: Set `conference-qr` to `display: flex` unconditionally (always visible)
- `applyConferenceLayout(false)`: Set `conference-qr` to `display: none`
- `updateCenterPanel`: Remove the conditional logic (lines ~1192-1196) that toggles `conference-qr` visibility based on activity state

### No Changes

- QR code generation (already works: 200x200, black on white)
- Animated URL display
- Participant counter
- Center and right column behavior
- Workshop mode behavior
