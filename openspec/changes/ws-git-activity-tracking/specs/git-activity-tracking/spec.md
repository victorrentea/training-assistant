## ADDED Requirements

### Requirement: Session state accumulates git file-open events
The daemon SHALL maintain a `git_repos` list in `ParticipantState`. Each entry has `url` (git remote URL), `branch`, and `files` (ordered list of unique file paths). When a `git_file_opened` event arrives, the daemon SHALL find or create the matching `(url, branch)` entry and append the file path if not already present.

#### Scenario: First file opened in a new session
- **WHEN** the daemon receives `{"type": "git_file_opened", "url": "https://github.com/org/repo", "branch": "main", "file": "src/App.java"}` and `git_repos` is empty
- **THEN** `git_repos` becomes `[{"url": "https://github.com/org/repo", "branch": "main", "files": ["src/App.java"]}]`

#### Scenario: Same file opened again — no duplicate
- **WHEN** the daemon receives a `git_file_opened` event for a file already present in the matching entry
- **THEN** `git_repos` is unchanged

#### Scenario: Different file in same repo+branch
- **WHEN** the daemon receives `git_file_opened` for a file not yet in an existing `(url, branch)` entry
- **THEN** the file is appended to the `files` list of that entry

#### Scenario: File in a different branch of the same repo
- **WHEN** the daemon receives `git_file_opened` for the same `url` but a different `branch`
- **THEN** a new entry is created for that `(url, branch)` combination

---

### Requirement: Git activity persisted to session state on disk
The daemon SHALL include `git_repos` in the session state JSON that is persisted to disk. On daemon restart with an existing session, the accumulated git activity SHALL be restored.

#### Scenario: Daemon restart preserves git activity
- **WHEN** the daemon restarts with an active session that had git activity
- **THEN** `GET /api/participant/git-activity` returns the same `git_repos` list as before the restart

---

### Requirement: Participant endpoint exposes git activity
The daemon SHALL expose `GET /api/participant/git-activity` that returns the accumulated `git_repos` list for the active session. The endpoint requires no authentication and is accessible to any caller.

#### Scenario: Active session with activity
- **WHEN** a participant calls `GET /api/participant/git-activity` and the session has accumulated git repos
- **THEN** the response is `{"git_repos": [{"url": "...", "branch": "...", "files": ["..."]}]}`

#### Scenario: No active session or no activity yet
- **WHEN** no session is active or no `git_file_opened` events have been received
- **THEN** the response is `{"git_repos": []}`

---

### Requirement: Host footer badge reflects accumulated git repo count
The daemon SHALL include `git_repos_count` in every host WS state push, equal to the number of distinct `(url, branch)` entries in `git_repos`. The host footer `⎇ N` badge SHALL display this count.

#### Scenario: Badge count matches accumulated repos
- **WHEN** the daemon has accumulated activity for 3 distinct `(url, branch)` pairs
- **THEN** the host footer shows `⎇ 3`

#### Scenario: Badge shows zero before any activity
- **WHEN** no `git_file_opened` events have been received
- **THEN** the host footer shows `⎇ 0`

---

### Requirement: File-based git activity mechanism is removed
The `activity-git-YYYY-MM-DD.md` file writing and reading SHALL be removed entirely. The daemon SHALL NOT read any such file. Any code path that produced or consumed this file SHALL be deleted.

#### Scenario: No file read on host state request
- **WHEN** the host requests its state from the daemon
- **THEN** no filesystem access to `activity-git-*.md` occurs; git data comes from session state
