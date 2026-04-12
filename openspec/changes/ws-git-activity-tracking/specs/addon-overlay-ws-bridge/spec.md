## ADDED Requirements

### Requirement: Addon sends git_file_opened WS message to daemon
The macOS addon (victor-macos-addons) SHALL send a `git_file_opened` message over the existing persistent WS connection to the daemon whenever the user opens a file in IntelliJ that differs from the last-sent file. The addon SHALL only deduplicate against its immediately previous message — it does not need to remember any older history.

#### Scenario: User opens a file in IntelliJ
- **WHEN** the user opens (or switches focus to) a file in IntelliJ and the combination `(url, branch, file)` differs from the last message sent
- **THEN** the addon sends `{"type": "git_file_opened", "url": "<git-remote-url>", "branch": "<branch>", "file": "<relative-file-path>"}` to the daemon via the existing WS connection

#### Scenario: Same file opened again — no duplicate sent
- **WHEN** the user opens the same file that was last sent
- **THEN** no message is sent (addon deduplicates against its last-sent value)

#### Scenario: Different file opened after first
- **WHEN** fileA was last sent and the user opens fileB
- **THEN** the addon sends `git_file_opened` for fileB; if the user returns to fileA, a new message for fileA is sent

#### Scenario: WS connection not available — message dropped silently
- **WHEN** the addon's WS connection to the daemon is not active when a file is opened
- **THEN** the message is dropped and no error surfaces to the user; the addon does not buffer unsent messages

---

### Requirement: Daemon handles git_file_opened inbound WS message
The daemon's `addon_bridge_client` SHALL handle the `git_file_opened` message type received from the addons WS server. On receipt, it SHALL forward the event to the git activity accumulator in session state.

#### Scenario: Valid git_file_opened message received
- **WHEN** the daemon receives `{"type": "git_file_opened", "url": "...", "branch": "...", "file": "..."}`
- **THEN** the daemon calls the session state accumulator and returns without error

#### Scenario: Unknown message type — ignored
- **WHEN** the daemon receives a WS message with an unrecognised `type`
- **THEN** the daemon logs a warning and continues without crashing
