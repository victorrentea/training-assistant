# Auto Version Stamping & Changelog

**Date:** 2026-03-20
**Problem:** `version.js` causes recurring merge conflicts; deploy notifications show only one commit message instead of full changelog.

---

## Part 1: Eliminate version.js merge conflicts

### Current state
- `static/version.js` is committed to git, containing `window.APP_VERSION = 'YYYY-MM-DD HH:MM';`
- Updated manually or by pre-commit hook before pushing
- Every branch touches this file → merge conflicts on nearly every PR
- No pre-commit hook is actually installed (`.git/hooks/pre-commit` does not exist); CLAUDE.md mentions one but it's stale

### New state
- Remove `static/version.js` from git tracking (`git rm --cached`)
- Add `static/version.js` to `.gitignore`
- Railway start command generates it at deploy time. The start command is configured **in the Railway dashboard** (no Procfile or railway.toml exists in this repo):
  ```
  echo "window.APP_VERSION = '$(date -u '+%Y-%m-%d %H:%M')';" > static/version.js && uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
  ```
- Local dev: add a fallback in `version-age.js` — if `APP_VERSION` is undefined, show `"dev"` (lowercase)
- `backend_version.py` continues to work unchanged (reads the file from disk at runtime; returns `""` when file is absent, which is acceptable for local dev)
- Update CLAUDE.md to remove the stale pre-commit hook reference about version stamping

### Files changed
- `.gitignore` — add `static/version.js`
- `static/version.js` — `git rm --cached`
- `static/version-age.js` — fallback: show `"dev"` instead of `""` when `APP_VERSION` is undefined
- Railway dashboard — update start command (manual step, documented in spec)
- `CLAUDE.md` — remove stale pre-commit hook reference

---

## Part 2: GitHub Action for deploy-info.json

### Purpose
Generate a changelog from commit messages on each push to master, and make it available to the web app via `static/deploy-info.json`.

### Trigger
On push to `master` branch.

### Permissions
The workflow needs `contents: write` to push commits back to master. Set explicitly in the workflow YAML:
```yaml
permissions:
  contents: write
```

### Action steps
1. Check if the triggering commit was made by `github-actions[bot]` — if so, exit early (defense-in-depth alongside `[skip ci]`)
2. Read `static/deploy-info.json` from the repo to get the previous deploy SHA
   - **First run (file doesn't exist):** use only HEAD's commit message as the changelog
3. Compute changelog: `git log --oneline <prev-sha>..HEAD` (excluding commits by `github-actions[bot]`)
4. Write `static/deploy-info.json`:
   ```json
   {
     "sha": "<HEAD-sha>",
     "timestamp": "2026-03-20 14:30",
     "changelog": [
       "fix: rename host badge from Points to Lessons",
       "fix: remove own-argument highlight for unified argument styling"
     ]
   }
   ```
5. Commit to master with message `chore: update deploy-info [skip ci]`
6. Push to master

### Guard against infinite loops
- `[skip ci]` in the commit message prevents ALL GitHub Actions from running on the Action's own commit (GitHub natively honors this for push/PR events since Feb 2021)
- Additionally, the Action checks if the triggering actor is `github-actions[bot]` and exits early (defense-in-depth)

### Spurious Railway deploy
The Action's commit to master WILL trigger a Railway deploy (~40-50s build). This is a no-op deploy (only `deploy-info.json` changed). **Accepted trade-off**: the extra deploy is harmless (same code, just updated JSON), and Railway has no built-in path-based deploy filtering. The watcher will detect the version change from the real deploy (version.js timestamp differs); the Action's no-op deploy won't change version.js timestamp since it was generated at Railway start time from `date -u`.

**Note:** The watcher may fire a second notification for the no-op deploy. To mitigate: the watcher should ignore deploys where the compare API returns 0 non-bot commits (i.e., only `chore: update deploy-info` commits).

### deploy-info.json in git
- The file IS tracked in git (committed by the Action only)
- Added to `.gitignore` so human branches don't accidentally modify it
- The Action uses `git add -f static/deploy-info.json` to bypass `.gitignore`
- Humans never touch this file → no merge conflicts

### Files changed
- `.github/workflows/deploy-info.yml` — new workflow
- `.gitignore` — add `static/deploy-info.json`

---

## Part 3: Watcher changelog in macOS notifications

### Current state
- `watch-deploy.sh` shows the single HEAD commit message in notifications
- `terminal-notifier -title "..." -message "$COMMIT_MSG"`

### New state
- When watcher detects master HEAD change (old SHA → new SHA), it fetches all commits between them:
  ```bash
  gh api "repos/$REPO/compare/${OLD_SHA}...${NEW_SHA}" \
    --jq '[.commits[].commit.message | split("\n")[0]] | join("\n")'
  ```
- This gives first-line-only of each commit message
- GitHub compare API caps at 250 commits — acceptable since deploys typically have 1-10 commits
- Stored in `COMMIT_MSG` (replacing the single commit message)
- Notification shows multi-line changelog:
  ```
  fix: rename host badge
  fix: remove own-argument highlight
  ```
- For countdown notifications: truncate to first 3 lines + "... +N more" if needed (macOS notifications have limited space)
- For success notification: show full changelog (still truncated if very long)
- **Filter out bot commits**: exclude lines matching `chore: update deploy-info` from the changelog to avoid noise from the Action's own commits
- **Ignore no-op deploys**: if after filtering, the changelog is empty (only bot commits), suppress the notification entirely

### Fallback
- If the compare API fails, fall back to single HEAD commit message (current behavior)

### Files changed
- `watch-deploy.sh` — replace `get_commit_message()` with `get_changelog()` using compare API

---

## Part 4: Local dev experience

- `static/version.js` won't exist in the repo after `git rm --cached`
- Running locally without it: `APP_VERSION` is undefined → `version-age.js` shows `"dev"`
- `backend_version.py` returns `""` → acceptable for local dev (no version mismatch warnings)
- Optionally, developers can generate it locally: `echo "window.APP_VERSION = 'dev';" > static/version.js`
- The file is gitignored so this won't affect git status

---

## Out of scope
- Showing changelog in the web UI (version-reload banner, etc.) — future enhancement
- GitHub Releases — not needed for this use case
- Persisting changelog history — `deploy-info.json` only tracks the latest deploy
