# Todo

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
