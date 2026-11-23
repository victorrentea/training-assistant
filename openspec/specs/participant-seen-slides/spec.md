## ADDED Requirements

### Requirement: The session keeps one "Seen slides" deck, each slide in the form it was shown
While a session is active, the daemon SHALL record every slide Victor Mac reports with a `slide_seen` message (shown 7 s with PowerPoint in front, and again when left; the deck is saved by then). A slide is identified by its deck file and PowerPoint's slide id, and versioned by the per-slide digest of `daemon/slides/pptx_slides.py` (slide XML and linked media, not layouts/theme). Without an active session the message SHALL be ignored.

#### Scenario: A slide shown for the first time
- **WHEN** a slide not in the session's registry is reported
- **THEN** it is appended (pages are in order of first showing) and the daemon sends Victor Mac `slide_seen_captured` with `change: "added"`

#### Scenario: The same slide shown again unchanged
- **WHEN** a slide is reported with the digest already recorded
- **THEN** nothing changes and no `slide_seen_captured` is sent

#### Scenario: The slide was edited and shown again
- **WHEN** a slide is reported with a new digest
- **THEN** its page is replaced in place once printed, and `slide_seen_captured` is sent with `change: "updated"`

#### Scenario: The same content in another deck
- **WHEN** a slide copied into another deck is shown
- **THEN** it is recorded as another slide

### Requirement: Pages come from PowerPoint's own print, never printed under the trainer's hands
A slide's page SHALL be the page of the deck PowerPoint last printed (`local_publish.py`'s `deck.pdf`) when that print holds the shown version. Otherwise the deck SHALL be printed, but only while PowerPoint is not the frontmost app and no slide show runs; decks outside the slides catalog are printed locally without upload. The assembled `seen.pdf` SHALL be stored in Railway's slides cache as slug `seen-slides-<session>` and announced with `slides_seen_updated {slug, count, updated_at}`; it is re-sent on every Railway reconnect.

#### Scenario: PowerPoint in front
- **WHEN** a shown version has no printed page and PowerPoint is frontmost
- **THEN** no print starts; the slide waits and is printed once PowerPoint leaves the front

#### Scenario: PowerPoint comes back to the front between two decks
- **WHEN** several decks wait for a print and PowerPoint becomes frontmost while the first one prints
- **THEN** the remaining decks are not printed; they wait until PowerPoint leaves the front again

#### Scenario: PowerPoint comes back to the front while the print waits its turn
- **WHEN** PowerPoint becomes frontmost while the print waits for another deck's print to end
- **THEN** it does not start; the same holds for the print held back after an auto-save, which goes back to waiting

#### Scenario: A print that failed
- **WHEN** the print of a deck fails (anything but "the deck is not open", "a slide show runs" or "PowerPoint in front")
- **THEN** that save of the deck is printed again ~5 min later and once more ~25 min after that, then no more until the deck is saved again

#### Scenario: Railway cannot be reached after the print
- **WHEN** the pages were printed but their upload failed
- **THEN** the printed pages are kept and serve the seen slides; the next try sends the whole deck without printing again

#### Scenario: The frontmost app cannot be read
- **WHEN** `lsappinfo` fails or times out
- **THEN** PowerPoint counts as frontmost and no such print starts

#### Scenario: A deck with hidden slides
- **WHEN** the deck holds slides marked "Hide Slide", which PowerPoint's print leaves out
- **THEN** no print is started for it (the pages would not line up with the slides); its shown slides wait until a save without hidden slides

### Requirement: Participants read the deck under "Seen slides"
The participant sidebar SHALL offer "Seen slides" (badge = page count), opening the deck in the Slides viewer at its last page, with follow turned off. New pages SHALL arrive live: a reader on the last page moves to the new last page, a reader who scrolled back stays. `/<session>/past-slides` SHALL open it. The materials zip SHALL include it as `slides/Slides seen.pdf`, and the offline copy links it as a deck. The host's "Clear slides" SHALL empty it.
