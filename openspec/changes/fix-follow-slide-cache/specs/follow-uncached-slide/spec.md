## ADDED Requirements

### Requirement: Follow seamlessly loads uncached slide
When a participant activates Follow and the host's current slide is not yet cached on Railway, the participant application SHALL wait for the download to complete (up to 35 seconds) and then display the slide at the host's current page. The participant SHALL see an informative loading state throughout, never a dead-end error.

#### Scenario: Participant clicks Follow — slide not cached — download completes within timeout
- **WHEN** participant clicks the Follow button and the host's current slide has `status: not_cached` on Railway
- **THEN** the participant UI SHALL show a "Preparing slide..." loading message immediately
- **AND** after ~1.5s of waiting, the loading message SHALL update to "Downloading slide from trainer's library…"
- **AND** once the check returns HTTP 200, the PDF SHALL load and scroll to the host's current page
- **AND** the slides overlay SHALL be open and the correct slide SHALL be active in the list

#### Scenario: Participant clicks Follow — slide not cached — download takes > 30s (daemon timeout)
- **WHEN** participant clicks the Follow button and the download does not complete within the daemon's 30s wait
- **THEN** the participant UI SHALL NOT show a permanent error
- **AND** when the `slides_cache_status` WS event subsequently fires (download eventually completed), the participant SHALL automatically retry the follow and load the slide

#### Scenario: Participant clicks Follow — slide already cached
- **WHEN** participant clicks Follow and the slide is already cached on Railway (`status: cached`)
- **THEN** the check SHALL return immediately, the slide SHALL load within 2 seconds, and the participant SHALL be scrolled to the host's current page

### Requirement: Railway proxy timeout sufficient for slide check
The Railway `proxy_to_daemon` call for `GET /api/slides/check/{slug}` SHALL use a timeout of 35 seconds (not the default 5 seconds), allowing the daemon's 30-second download wait to complete before the proxy times out.

#### Scenario: Daemon-side download takes up to 30 seconds
- **WHEN** `GET /api/slides/check/{slug}` is called and the daemon triggers a Railway PDF download that takes up to 30 seconds
- **THEN** Railway SHALL NOT return 503 due to proxy timeout before the daemon responds
- **AND** Railway SHALL forward the daemon's 200 response to the participant after the download completes
