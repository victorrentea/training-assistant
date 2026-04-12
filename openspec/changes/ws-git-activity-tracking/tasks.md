## 1. Session State — GitRepoActivity model

- [x] 1.1 Add `GitRepoActivity` Pydantic model (`url: str`, `branch: str`, `files: list[str]`) to `daemon/participant/state.py`
- [x] 1.2 Add `git_repos: list[GitRepoActivity]` field (default empty list) to `ParticipantState`
- [x] 1.3 Add `accumulate_git_file(url, branch, file)` method to `ParticipantState` that inserts or updates the matching entry with deduplication
- [x] 1.4 Ensure `git_repos` is included when `ParticipantState` is serialised to / deserialised from the session JSON on disk

## 2. Addon Bridge — inbound WS message handler

- [x] 2.1 Add `GitFileOpenedMsg` Pydantic model (`type: Literal["git_file_opened"]`, `url: str`, `branch: str`, `file: str`) to `daemon/ws_messages.py`
- [x] 2.2 In `daemon/addon_bridge_client.py`, add a branch in the inbound message dispatcher to handle `type == "git_file_opened"` by calling `participant_state.accumulate_git_file(...)`

## 3. Participant REST endpoint

- [x] 3.1 Add `GitActivityResponse` Pydantic model (`git_repos: list[GitRepoActivity]`) to `daemon/participant/router.py`
- [x] 3.2 Implement `GET /api/participant/git-activity` endpoint that returns `GitActivityResponse` from `participant_state.git_repos`

## 4. Host WS state — source from session state

- [x] 4.1 In `daemon/host_state_router.py`, replace the call to `_build_git_repos_fields()` with a read from `participant_state.git_repos` to populate `git_repos_count` in the host WS push
- [x] 4.2 Delete the `_build_git_repos_fields()` function and the `_GIT_LINE_RE` regex from `host_state_router.py`

## 5. Remove file-based mechanism

- [x] 5.1 Delete all file-write code in the daemon (or any path) that writes `activity-git-*.md` — confirm no such write exists in daemon (currently written by the addon, not daemon); if the file path is referenced anywhere in daemon for reading, remove all references
- [x] 5.2 Remove the file-read path in `host_state_router.py` (`activity-git-{date}.md` open/read block)
- [x] 5.3 Confirm no remaining import or reference to `activity-git` pattern in the codebase

## 6. macOS Addon update (external repo)

- [x] 6.1 In `victor-macos-addons`, replace the file-append logic with a call to send `{"type": "git_file_opened", "url": ..., "branch": ..., "file": ...}` over the existing WS connection
- [x] 6.2 Implement last-sent deduplication in the addon (store the last sent tuple; skip send if identical)
- [x] 6.3 Remove any file-write code for `activity-git-*.md` from the addon

## 7. Verification

- [ ] 7.1 Manually open a file in IntelliJ, confirm `GET /api/participant/git-activity` returns it
- [ ] 7.2 Confirm the host footer `⎇ N` badge increments when a new repo+branch is opened
- [ ] 7.3 Confirm re-opening the same file does not duplicate it in the response
- [ ] 7.4 Restart the daemon mid-session; confirm git activity survives restart
- [ ] 7.5 Confirm no `activity-git-*.md` file is created or read during a session
