# Conference Mode: QR Code Always Visible in Left Panel

## Problem

In conference mode, the `conference-qr` container (QR code + URL + participant count) in the left column is only shown when an activity is active. Additionally, tab content (especially Code Review) can overflow and obscure the QR area. The QR should be permanently visible so conference attendees can join at any time.

## Design

In conference mode, the left column (`host-col-left`) splits into a CSS grid with three rows:

1. **Top half (1fr)**: New wrapper div around tab bar + all tab content panels, with internal scroll
2. **Bottom half (1fr)**: `conference-qr` container, always visible
3. **Auto row**: `.left-status-bar` pinned at the bottom

### HTML Changes (host.html)

Add a wrapper `<div class="left-tabs-wrapper">` around the tab bar (`.tab-bar`) and all tab content panels (`#tab-content-poll` through `#tab-content-debate`). This gives the grid exactly two meaningful content rows plus the status bar.

### CSS Changes (host.css)

Add conference-mode class `.conference-layout` on `.host-col-left`:
- `display: grid; grid-template-rows: 1fr 1fr auto`
- `.left-tabs-wrapper` gets `overflow-y: auto; min-height: 0` to scroll within its half
- `conference-qr` takes the second row
- `.left-status-bar` takes the auto row

### JS Changes (host.js)

- `applyConferenceLayout(true)`: Add `conference-layout` class to `.host-col-left`; set `conference-qr` to `display: flex` unconditionally; hide `#conference-pax-display` (redundant — QR container already shows "N Joined")
- `applyConferenceLayout(false)`: Remove `conference-layout` class; set `conference-qr` to `display: none`
- `updateCenterPanel` function: Remove the conditional logic that toggles `conference-qr` visibility based on activity state

### Elements addressed

- `#conference-pax-display`: Hidden when QR is always visible (its "N connected" is redundant with QR's "N Joined" counter)
- `.left-status-bar`: Placed in a third `auto`-sized grid row, stays pinned at bottom
- `.conference-qr-container` `flex: 1`: Dead CSS in grid mode, can be cleaned up

### No Changes

- QR code generation (already works: 200x200, black on white)
- Animated URL display
- Center and right column behavior
- Workshop mode behavior
