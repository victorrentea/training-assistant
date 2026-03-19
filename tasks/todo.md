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
