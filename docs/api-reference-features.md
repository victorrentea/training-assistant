# API Reference Feature IDs

Canonical `x-feature` IDs used for generated `API.md` grouping.

## IDs

- `session_management`
- `slides`
- `activity`
- `identity`
- `poll`
- `wordcloud`
- `qa`
- `codereview`
- `debate`
- `scores_leaderboard`
- `emoji`
- `paste_upload`
- `notes_summary`
- `feedback`
- `transcription`
- `infrastructure` — Internal daemon↔railway transport plumbing (proxy, ping, session identity, code timestamp, broadcast/send_to_host wrappers)

## Usage

- REST operations: set `x-feature` in exported OpenAPI (daemon enriches OpenAPI schema in `daemon/openapi_contract_metadata.py`).
- WS messages: set `x-feature` on every message in:
  - `docs/participant-ws.yaml`
  - `docs/host-ws.yaml`

## Notes

- Optional note field: `x-doc-notes` (list of strings).
- `summary` and `description` are also exported by the generator.
- Generated reference command:
  - `python3 scripts/generate_apis_md.py --output API.md`
