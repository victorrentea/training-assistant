# Fix: agenda not picked up live (only after daemon restart)

## Root cause
Notes/summary are re-probed every main-loop iteration (`_build_notes_summary_probe`) and
broadcast over WS on change. The agenda path (`misc_state.agenda_docx_path`) is only set at
daemon startup (`__main__.py:858`) and session-create (`:1156`) — never re-probed in the loop.
An agenda dropped after startup leaves the path stale → `/agenda` 404s, `has_agenda` stays
false, and no WS push notifies connected participants (they don't poll `/state`). Restart
re-scans the folder, which is why it only appears then.

## Fix (mirror the notes/summary mechanism exactly)
- [ ] Add `AgendaUpdatedMsg(has_agenda: bool)` to `daemon/ws_messages.py`; register in
      `PARTICIPANT_MESSAGES` + `PARTICIPANT_MESSAGE_FEATURES` (`notes_summary`). Participant-only.
- [ ] Extend `_build_notes_summary_probe` with `agenda_file` + `agenda_mtime_ns`.
- [ ] Extend `_probe_change_parts` to emit `"agenda"`; extend `_log_notes_summary_probe`.
- [ ] In the main loop change-block: keep `misc_state.agenda_docx_path` fresh from the probe
      (helper `_agenda_path_from_probe`).
- [ ] Extend `_broadcast_notes_summary_counts` to broadcast `AgendaUpdatedMsg` (and include
      agenda in the all-absent early-return guard).
- [ ] Frontend `static/participant.html`: add `case 'agenda_updated'` handler (show/hide nav,
      mark `_agendaDirty`, reload if currently on agenda view).
- [ ] Update `docs/participant-ws.yaml` (message def + channel `oneOf`).
- [ ] Regenerate `API.md` via `python3 scripts/generate_apis_md.py --output API.md`.

## Tests
- [ ] Unit test (`tests/daemon/`): probe detects agenda add/remove; `_probe_change_parts`
      returns `agenda`; `_broadcast_notes_summary_counts` emits `AgendaUpdatedMsg`.
- [ ] Existing WS contract test passes (registry <-> YAML).
- [ ] Browser proof: drop agenda.docx mid-session, agenda nav appears live (screenshot).

## Review
Done. Agenda now behaves exactly like notes/ai-summary: the main-loop probe
(`_build_notes_summary_probe`) tracks the agenda .docx path + mtime, change-detection
emits an `agenda` part, the loop keeps `misc_state.agenda_docx_path` live, and the daemon
broadcasts `AgendaUpdatedMsg(has_agenda)`. The participant `agenda_updated` handler shows/
hides the nav and re-fetches. The all-absent broadcast guard was narrowed to the genuine
first ("initial") probe so a present->absent removal still broadcasts (navs hide live).

Verified:
- 19 daemon unit tests (probe / change-parts / broadcast / guard) — pass
- WS contract tests (registry <-> participant-ws.yaml) — pass
- Hermetic Docker E2E (`test_agenda_live`): nav hidden -> appears live on drop (no restart)
  -> hides live on remove — all 3 steps pass
- ruff / vulture / pyright clean; API.md regenerated

Out of scope (pre-existing, flagged): `tests/docker/test_notes_summary_counts.py` (nightly)
uses stale `#notes-btn`/`#summary-btn` selectors removed in an earlier UI refactor — already
broken on master, unrelated to this change.
