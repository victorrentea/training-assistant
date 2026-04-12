## ADDED Requirements

### Requirement: Participant can retrieve accumulated slide viewing history
The daemon SHALL expose `GET /api/participant/slide-history` returning the accumulated list of slides viewed during the current session. Each entry SHALL include the PowerPoint file name, 1-based slide number, and cumulative seconds viewed. The endpoint SHALL be freely accessible (no authentication required). The response SHALL use a typed Pydantic model `SlideHistoryResponse` with a `slides` field.

#### Scenario: No slides have been viewed yet
- **WHEN** a participant calls `GET /api/participant/slide-history` before any slide activity has been recorded
- **THEN** the response is `{"slides": []}` with HTTP 200

#### Scenario: Slides have been viewed during the session
- **WHEN** a participant calls `GET /api/participant/slide-history` after the trainer has shown slides
- **THEN** the response contains one entry per unique `(file_name, page)` pair, each with the cumulative `seconds` viewed, and HTTP 200

#### Scenario: Multiple slides from different decks
- **WHEN** the session includes slides from more than one PowerPoint file
- **THEN** the response includes entries for all files, each with the correct `file_name`, `page`, and `seconds`

### Requirement: Participant slide history drops down on click and auto-collapses
The participant UI SHALL fetch `GET /api/participant/slide-history` and display the returned list below the current slide view when the participant clicks the slides item in the slides dock. The list SHALL automatically collapse 30 seconds after being displayed. Clicking the slides item again SHALL re-fetch the endpoint, re-display the list, and restart the 30-second collapse timer. If the response contains no slides, the list area SHALL NOT be rendered.

#### Scenario: Participant clicks slides item — history appears
- **WHEN** a participant clicks the slides item in the slides dock
- **THEN** the UI calls `GET /api/participant/slide-history`, renders the returned slide list below the current slide, and starts a 30-second collapse timer

#### Scenario: List auto-collapses after 30 seconds
- **WHEN** the slide history list has been visible for 30 seconds without another click
- **THEN** the list is removed from view automatically

#### Scenario: Participant clicks slides item again — history re-expands
- **WHEN** the participant clicks the slides item while the list is collapsed (or after it auto-collapsed)
- **THEN** the UI re-fetches `GET /api/participant/slide-history`, renders the fresh list, and restarts the 30-second timer

#### Scenario: History is empty — no list rendered
- **WHEN** `GET /api/participant/slide-history` returns `{"slides": []}`
- **THEN** no history list area is shown (the collapse timer still runs but clears nothing)
