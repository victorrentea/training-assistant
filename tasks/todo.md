# Todo

## Backlog item: GH#67 participant slides viewer (PDF)

- [x] Add backend slide metadata endpoint `GET /api/slides`
- [x] Extend daemon→backend status payload to carry slide list metadata
- [x] Load slide manifest from active session folder in daemon and normalize entries
- [x] Add participant "Slides" UI with PDF.js viewer, selector, and download action
- [x] Persist/restore current slide page per slug in `localStorage`
- [x] Auto-refresh slide metadata and reload viewer when source changes
- [x] Add/adjust automated tests for backend + daemon helpers
- [x] Track request completion in `backlog.md`
- [x] Run targeted tests and capture proof in review section

## Follow-up request: include local materials/slides PDFs in Slides combo

- [x] Discover PDFs from local `training-assistant/materials/slides` directory
- [x] Expose discovered files through public slide-file endpoint
- [x] Merge local discovered slides into `/api/slides` response
- [x] Add tests for local discovery + file serving + merge behavior
- [x] Run targeted tests

## Backlog item: periodic timestamps in transcription file

- [x] Inspect existing transcription parser format in `quiz_core.py`
- [x] Implement a small Python script to append timestamp labels periodically (3s default for testing)
- [x] Make marker lines parser-friendly for existing transcript loading logic
- [x] Add automated tests for line format and periodic append behavior
- [x] Run targeted tests and a short local smoke run
- [x] Mark backlog item done

## Follow-up request: run for 3 minutes instead of 3 markers

- [x] Replace marker-count stop with duration-based stop in script CLI
- [x] Set default run duration to 3 minutes
- [x] Update tests for duration-based stopping
- [x] Track follow-up as done in `backlog.md`
- [x] Run targeted tests

## Follow-up request: append empty lines every 3 seconds

- [x] Change appender to write only blank lines
- [x] Remove unused marker text CLI options
- [x] Update focused tests for blank-line behavior
- [x] Track follow-up as done in `backlog.md`
- [x] Run targeted tests

## Follow-up request: append empty line + first-line-like timestamp prefix

- [x] Read first transcription line shape and infer formatting template
- [x] Append one empty line, then a timestamp prefix with a single space payload
- [x] Keep run interval and duration behavior unchanged
- [x] Update focused tests for inferred pattern and append output
- [x] Track follow-up as done in `backlog.md`
- [x] Run targeted tests

## Follow-up request: silence per-insert console logs

- [x] Remove per-insert print statements from runtime loop
- [x] Keep startup and shutdown info logs
- [x] Add regression test for compact console output
- [x] Track follow-up as done in `backlog.md`
- [x] Run targeted tests

## Follow-up request: merge timestamp appender into quiz daemon

- [x] Integrate transcript timestamp appender into `quiz_daemon.py`
- [x] Ensure missing transcript file logs one startup error only
- [x] Keep daemon resilient by disabling appender after append I/O failures
- [x] Add focused daemon tests for one-time error logging and interval append
- [x] Run targeted tests
- [x] Track follow-up as done in `backlog.md`

## Follow-up request: single newline + timestamp-only line

- [x] Remove speaker label from injected timestamp line
- [x] Use single newline before each injected timestamp line
- [x] Update focused tests for daemon + script behavior
- [x] Track follow-up as done in `backlog.md`
- [x] Run targeted tests

## Backlog item: poll generate button has inconsistent labels

- [x] Ensure only two labels are ever used for `#gen-quiz-btn`
- [x] Align initial HTML label with JS label logic
- [x] Initialize label state on page load
- [x] Add e2e regression for transcript/topic label switching
- [x] Mark item done in `backlog.md`
- [x] Run targeted tests

## Follow-up request: merge `scripts/` timestamp code into daemon module

- [x] Move timestamp helpers from `scripts/` to `daemon/transcript_timestamps.py`
- [x] Switch `quiz_daemon.py` imports to daemon module
- [x] Update timestamp tests to import daemon module
- [x] Remove obsolete `scripts/` files
- [x] Track follow-up as done in `backlog.md`
- [x] Run targeted tests

## Backlog item: Q&A input/button heights must match

- [x] Align host Q&A input height with submit button height
- [x] Align participant Q&A input height with submit button height
- [x] Add focused e2e regression for control-height alignment
- [x] Capture screenshot proof for host and participant Q&A rows
- [x] Mark item done in `backlog.md`
- [x] Run targeted tests

## Backlog items: Q&A host actions + transcript-prompt hardening

- [x] Host Q&A actions: `Answered` label, trash icon for delete, renamed clear-all action
- [x] Host Q&A edit flow: remove brittle inline text serialization and read current text from DOM
- [x] Prompt hardening: warn about transcript gibberish/repetition/nonsense
- [x] Prompt behavior: enforce transcript-topics-first, then references for depth
- [x] Add focused tests for Q&A host actions and prompt wording
- [x] Capture screenshot proof for host Q&A action labels/icons
- [x] Mark all three backlog items done in `backlog.md`
- [x] Run targeted tests

## Backlog item: live deploy-age version label on host and participant

- [x] Implement shared elapsed-time formatter/updater in `static/version-age.js`
- [x] Wire both `static/host.html` and `static/participant.html` to use shared renderer
- [x] Add focused e2e regression for elapsed label + under-day live update
- [x] Capture host and participant screenshot proof
- [x] Mark item done in `backlog.md`
- [x] Run targeted tests

## Backlog item: avoid redundant reindexing on local-agent restart

- [x] Add per-file hash manifest (`.index-manifest.json`) in materials root
- [x] Replace full startup indexing with incremental startup sync
- [x] Reindex only changed/new files and remove deleted files from index
- [x] Update manifest after startup sync and file-watcher updates
- [x] Add focused tests for unchanged-skip and changed/new/removed flows
- [x] Mark item done in `backlog.md`
- [x] Capture non-visual proof via test logs
- [x] Run targeted tests

## Backlog item: daemon reconnects automatically after server disconnect

- [x] Add bounded server HTTP timeout to avoid daemon hangs during disconnects
- [x] Normalize invalid JSON/timeout transport failures to retryable `RuntimeError`
- [x] Add reconnect state transitions in daemon loop (disconnect once, reconnect once)
- [x] Add focused tests for HTTP helper wrapping and daemon disconnect/reconnect flow
- [x] Mark item done in `backlog.md`
- [x] Capture non-visual proof via test logs
- [x] Run targeted tests

## Backlog item: frontend detects backend deploy-version mismatch and prompts reload

- [x] Verify host and participant both initialize shared reload guard (`static/version-reload.js`)
- [x] Verify mismatch check is executed from websocket `state` updates in both UIs
- [x] Run focused e2e regression for mismatch banner + stop action
- [x] Mark item done in `backlog.md`
- [x] Capture non-visual proof via test output

## Direct request: Pet Clinic owner search by name

- [x] Review existing `/.github/petclinic-instructions.md` discovery baseline
- [x] Open Pet Clinic at `http://localhost:4200/petclinic/`
- [x] Navigate through `OWNERS` → `SEARCH`
- [x] Search owner by last name and capture the visible result
- [x] Update `/.github/petclinic-instructions.md` with newly confirmed behaviors

## Direct request: Pet Clinic try editing an owner

- [x] Reuse the verified `George Franklin` owner flow
- [x] Open `Edit Owner` and inspect the form fields/buttons
- [x] Change an owner field and save successfully
- [x] Restore the original owner value after verification
- [x] Update `/.github/petclinic-instructions.md` with confirmed edit-flow behavior

## Direct request: Pet Clinic add, edit, and delete a pet

- [x] Reuse the verified `George Franklin` owner flow
- [x] Open `Add New Pet` and inspect the pet form
- [x] Create a disposable pet and confirm it appears for the owner
- [x] Edit the created pet and confirm the update appears
- [x] Delete the created pet and confirm it disappears
- [x] Update `/.github/petclinic-instructions.md` with confirmed pet lifecycle behavior

## Direct request: Pet Clinic hierarchical navigation structure

- [x] Revisit the current Pet Clinic discovery baseline
- [x] Explore all top-level navbar sections and submenu entries
- [x] Confirm major child routes for owners, pets, visits, veterinarians, pet types, and specialties
- [x] Capture confirmed page-level buttons and form patterns
- [x] Update `/.github/petclinic-instructions.md` with a hierarchical page map and navigation notes

## Direct request: GH66 PPTX daemon for obfuscated PDF publishing

- [x] Add backend state + API endpoints for current published slides URL
- [x] Expose slides URL in existing status/state payloads for host/participants
- [x] Implement `slides_daemon.py` for PPTX change detection, CPU guard, export, publish, and backend sync
- [x] Add focused tests for new API and daemon core logic
- [x] Run targeted tests and capture non-visual proof logs
- [x] Mark GH66 item done in `backlog.md`

## Direct request: track full slides catalog and regenerate Materials Slides PDFs

- [x] Add complete tracked PPTX catalog from `https://victorrentea.ro/slides/` to repo config
- [x] Update `slides_daemon.py` to process catalog entries from multiple subfolders
- [x] Default copy output to `materials/slides` and regenerate target PDF on source PPTX mtime change
- [x] Keep optional backend publish flow (sync only when configured)
- [x] Add focused tests for catalog loading and target PDF routing
- [x] Run targeted tests and capture non-visual proof logs
- [x] Mark direct request done in `backlog.md`

## Review

- Added `scripts/append_transcription_timestamps.py` with 3s default interval and parser-compatible format.
- Added tests in `test_append_transcription_timestamps.py` for format, append count, and interval guard; syntax checks pass (`get_errors`).
- Backlog item marked done in `backlog.md`.
- Follow-up applied: script now runs for 3 minutes by default (`--run-minutes`, default 3.0) instead of marker-count stopping.
- Verified with `python3 -m pytest -q test_append_transcription_timestamps.py` (4 passed).
- Follow-up applied: script now appends empty lines only (no timestamp marker text).
- Verified again with `python3 -m pytest -q test_append_transcription_timestamps.py` (4 passed).
- Follow-up applied: script now appends an empty line plus a timestamp prefix matching first-line style, ending with `\t `.
- Verified with `python3 -m pytest -q test_append_transcription_timestamps.py` (5 passed).
- Follow-up applied: script no longer logs on every insert; only startup/shutdown info remains.
- Verified with `python3 -m pytest -q test_append_transcription_timestamps.py` (6 passed).
- Follow-up applied: timestamp append logic is now integrated in `quiz_daemon.py` and startup missing-file errors are emitted once.
- Verified with `python3 -m pytest -q test_append_transcription_timestamps.py test_quiz_daemon_timestamp.py` (8 passed).
- Follow-up applied: injected line now contains only the timestamp (no speaker) and uses single-newline separation.
- Verified with `python3 -m pytest -q test_append_transcription_timestamps.py test_quiz_daemon_timestamp.py` (8 passed).
- Backlog item fixed: host generate button labels are restricted to `Generate from transcript` and `Generate on topic`.
- Verified with `python3 -m pytest -q test_e2e.py -k generate_button_uses_only_transcript_or_topic_labels` (1 passed).
- Follow-up applied: timestamp helpers are now daemon-owned in `daemon/transcript_timestamps.py`; `scripts/` helper files removed.
- Verified with `python3 -m pytest -q test_append_transcription_timestamps.py test_quiz_daemon_timestamp.py` (8 passed).
- Backlog item fixed: Q&A input/button heights now match in host and participant views.
- Verified with `python3 -m pytest -q test_e2e.py -k qa_input_and_button_heights_are_aligned_with_screenshots` (1 passed).
- Proof screenshots: `docs/superpowers/specs/qa-height-host.png`, `docs/superpowers/specs/qa-height-participant.png`.
- Backlog items fixed: Q&A host actions (`Answered`, trash icons, reliable edit) and transcript-first/noisy-transcript prompt guidance.
- Verified with `python3 -m pytest -q test_e2e.py -k "host_edits_question_participant_sees_update or host_qa_action_labels_icons_and_edit_with_quotes"` (2 passed, 27 deselected).
- Verified with `python3 -m pytest -q test_quiz_core_prompt.py` (2 passed).
- Proof screenshot: `docs/superpowers/specs/qa-host-actions.png`.
- Backlog item fixed: deploy version label now shows elapsed age and updates live under one day in both host and participant UIs.
- Verified with `python3 -m pytest -q test_e2e.py -k version_tag_shows_elapsed_time_and_updates_under_day` (1 passed, 27 deselected).
- Proof screenshots: `docs/superpowers/specs/version-age-host.png`, `docs/superpowers/specs/version-age-participant.png`.
- Backlog item fixed: local agent startup indexing now skips unchanged files using per-file SHA-256 manifest and only reindexes changed/new files.
- Verified with `python3 -m pytest -q test_daemon_indexer_incremental.py` (2 passed).
- Proof logs: `/tmp/indexer_incremental_tests.log`.
- Backlog item fixed: daemon now survives transient server disconnects/redeploys and reconnects automatically without restart.
- Verified with `python3 -m pytest -q test_quiz_core_http_helpers.py test_quiz_daemon_reconnect.py` (4 passed).
- Proof logs: `/tmp/reconnect_item_tests.log`.
- Backlog item fixed: host and participant detect backend/frontend version mismatch and show a stop-capable auto-reload prompt.
- Verified with `python3 -m pytest -q test_e2e.py -k version_mismatch_shows_reload_prompt_and_stop_prevents_auto_reload` (1 passed, 28 deselected).
- Pet Clinic exploration complete: searched `Franklin` on `http://localhost:4200/petclinic/owners` and confirmed result `George Franklin`.
- Proof screenshots: `docs/superpowers/specs/petclinic-owner-search-franklin.png`, `docs/superpowers/specs/petclinic-owner-george-franklin-detail.png`.
- Updated `/.github/petclinic-instructions.md` with verified navbar, owner search, routing, selectors, and detail-page observations.
- Pet Clinic edit exploration complete: opened `Edit Owner` for `George Franklin`, changed `City` from `Madison` to `Madison Test`, saved successfully, then restored `City` back to `Madison`.
- Proof screenshots: `docs/superpowers/specs/petclinic-owner-edit-form.png`, `docs/superpowers/specs/petclinic-owner-edit-after-save.png`.
- Updated `/.github/petclinic-instructions.md` with verified owner edit route, form fields, save behavior, and post-save navigation observations.
- Pet Clinic pet lifecycle exploration complete: added `Copilot Temp Pet`, renamed it to `Copilot Temp Pet Updated`, then deleted it from `George Franklin`.
- Proof screenshots: `docs/superpowers/specs/petclinic-add-pet-form.png`, `docs/superpowers/specs/petclinic-pet-after-add.png`, `docs/superpowers/specs/petclinic-edit-pet-form.png`, `docs/superpowers/specs/petclinic-pet-after-edit.png`, `docs/superpowers/specs/petclinic-pet-after-delete.png`.
- Updated `/.github/petclinic-instructions.md` with verified add-pet route, edit-pet route, button-state behavior, and immediate-delete behavior.
- Pet Clinic navigation exploration complete: confirmed the top-level hierarchy for `HOME`, `OWNERS`, `VETERINARIANS`, `PET TYPES`, and `SPECIALTIES`, plus child flows for owner detail, owner edit, add pet, edit pet, add visit, add/edit vet, and reference-data edit states.
- Updated `/.github/petclinic-instructions.md` with a menu-first navigation tree, page-level buttons, route inventory, and form-pattern notes for owners, pets, visits, vets, pet types, and specialties.
- GH66 implemented: backend now stores and serves `slides_current` via new endpoints (`POST/DELETE /api/slides/current`, `GET /api/slides/current`), and includes this payload in WS host/participant state + `/api/status` + state snapshot restore/serialize.
- Added `slides_daemon.py`: watches `.pptx`, processes one file per cycle, skips export under CPU pressure, converts (`google_drive` or `libreoffice`), publishes obfuscated `slug.pdf`, and pushes URL to backend.
- Verified with `python3 -m pytest -q tests/test_slides_api.py tests/test_slides_daemon.py` (7 passed).
- Verified with `python3 -m pytest -q tests/test_main.py -k "session_snapshot_returns_participants_and_scores or session_snapshot_requires_auth"` (2 passed, 118 deselected).
- Proof logs: `/tmp/gh66_tests.log`.
- Backlog item fixed: GH#67 participant Slides viewer is now available with PDF.js, download action, page persistence, and update-aware reloads.
- Backend/daemon wiring added: `/api/slides` endpoint, daemon slide-manifest normalization, and `quiz-status` slide metadata propagation.
- Verified with `pytest -q tests/test_main.py -k "slides or quiz_request_reports_has_slides_flag"` (3 passed).
- Verified with `pytest -q tests/test_quiz_core.py -k "post_status"` (4 passed).
- Verified with `pytest -q tests/test_daemon_state.py -k "slides_manifest"` (2 passed).
- Verified with `pytest -q tests/test_e2e_quiz_summary.py -k "update_with_session or poll_after_request"` (2 passed).
- Frontend syntax check: `node --check static/participant.js`.
- Proof screenshot: `docs/superpowers/specs/gh67-slides-viewer.png`.
- Follow-up implemented: `/api/slides` now auto-includes PDFs from local `training-assistant/materials/slides`, and serves them via `/api/slides/file/{slug}` for participant access.
- Verified with `pytest -q tests/test_slides_api.py` (4 passed).
- Verified with `pytest -q tests/test_main.py -k "api_slides_is_empty_by_default or quiz_status_updates_slides_and_api_returns_normalized_data or quiz_request_reports_has_slides_flag"` (3 passed, 120 deselected).
- Added full deck catalog file `daemon/materials_slides_catalog.json` with 25 slide sources mapped to target PDFs in Materials Slides.
- Updated `slides_daemon.py` to support catalog mode (multiple source subfolders), default local output `materials/slides`, and optional backend sync.
- Verified with `python3 -m pytest -q tests/test_slides_daemon.py tests/test_slides_api.py` (9 passed).
- Proof logs: `/tmp/slides_catalog_tests.log`.
