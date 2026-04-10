## ADDED Requirements

### Requirement: Daemon reverse-geocodes participant coordinates once
When the daemon receives a participant location that is a raw `lat,lon` coordinate pair, it SHALL call the Nominatim reverse-geocoding API server-side and store the resolved city/country label in the participant state. The call SHALL be made at most once per participant per session.

#### Scenario: New participant submits coordinates
- **WHEN** a participant posts a location matching `^-?\d+\.?\d*,\s*-?\d+\.?\d*$`
- **THEN** the daemon stores the raw coordinates in `participant_state.locations[pid]`
- **AND** the daemon asynchronously calls Nominatim `/reverse` with those coordinates
- **AND** upon success stores the resolved label (e.g. "Bucharest, RO") in `participant_state.cities[pid]`
- **AND** broadcasts an updated participant state event to the host including the `city` field

#### Scenario: Nominatim call fails or times out
- **WHEN** the Nominatim API returns an error or times out
- **THEN** `participant_state.cities[pid]` SHALL remain unset (or retain its previous value)
- **AND** the host SHALL display the raw coordinate string as a fallback

#### Scenario: Participant submits non-coordinate location
- **WHEN** a participant posts a location that is NOT a coordinate pair (e.g. a city name or timezone string)
- **THEN** the daemon SHALL store the string directly in both `locations[pid]` and `cities[pid]` without calling Nominatim

#### Scenario: Same participant re-submits location
- **WHEN** a participant who already has a resolved `cities[pid]` entry posts a new location
- **THEN** the daemon SHALL geocode the new coordinates and overwrite `cities[pid]`

### Requirement: Host displays pre-resolved city label without browser geocoding
The host UI SHALL use the `city` field from participant state for location display and SHALL NOT make any Nominatim API calls from the browser for participant location resolution.

#### Scenario: Host receives participant with resolved city
- **WHEN** the host receives a participant state update containing a non-empty `city` field
- **THEN** the host SHALL display the `city` value in the participant list location column

#### Scenario: Host receives participant with unresolved city
- **WHEN** the host receives a participant state update with no `city` field (geocoding pending or failed)
- **THEN** the host SHALL display the raw `location` string (or nothing if empty)
