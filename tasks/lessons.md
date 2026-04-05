# Lessons

- 2026-03-19: When sharing a quick-run example, prefer duration-based flags for human workflows (for example `--run-minutes`) instead of count-based flags (for example fixed marker ticks) unless the user explicitly asks for count-limited behavior.
- 2026-03-19: For transcript heartbeat/filler requests, follow the simplest requested output shape (blank lines if requested) and avoid adding extra marker payload.
- 2026-03-19: When requested to mirror transcript formatting, infer the line template from the first line and preserve spacing/separators exactly.
- 2026-03-19: For periodic append scripts, avoid high-frequency console logs by default; keep output to start/stop summaries.
- 2026-03-19: For daemon-integrated optional features, resolve prerequisites once at startup and emit at most one startup error when prerequisites are missing.
- 2026-03-19: Keep injected transcript heartbeat lines minimal: timestamp-only payload and no extra blank-line separators unless explicitly requested.
- 2026-03-19: If functionality becomes daemon-owned, relocate helper modules under `daemon/` promptly and remove leftover standalone script packages.
- 2026-03-19: After finishing any backlog item, provide proof artifacts before marking done (screenshots by default; test/log captures for non-visual work).
- 2026-03-19: After finishing a task or when blocked and needing user attention, play a completion/attention sound automatically.
- 2026-03-26: For PowerPoint automation during live sessions, avoid UI focus theft: do not use `activate` or force-open files; export only already-open presentations in background-safe mode.
- 2026-04-06: In daemon routers, never send raw WS dicts to host/participants; always use typed Pydantic message models via `daemon.ws_publish` (`broadcast`/`notify_host`) to satisfy contract tests and keep AsyncAPI parity.
