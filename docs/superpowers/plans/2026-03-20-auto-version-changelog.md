# Auto Version Stamping & Changelog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate version.js merge conflicts by generating it at deploy time, and add multi-commit changelog to deploy notifications.

**Architecture:** Three independent changes: (1) remove version.js from git and generate at Railway build time, (2) add GitHub Action to produce deploy-info.json with changelog, (3) update watch-deploy.sh to show multi-commit changelog in macOS notifications.

**Tech Stack:** Bash, GitHub Actions YAML, vanilla JS

**Spec:** `docs/superpowers/specs/2026-03-20-auto-version-changelog-design.md`

---

### Task 1: Remove version.js from git and add gitignore entries

**Files:**
- Modify: `.gitignore`
- Untrack: `static/version.js`

- [ ] **Step 1: Add gitignore entries for version.js and deploy-info.json**

Append to `.gitignore`:
```
static/version.js
static/deploy-info.json
```

- [ ] **Step 2: Untrack version.js from git**

```bash
git rm --cached static/version.js
```

- [ ] **Step 3: Create a local version.js for dev use**

```bash
echo "window.APP_VERSION = 'dev';" > static/version.js
```

This file is now gitignored, so it won't show in git status.

- [ ] **Step 4: Verify git status**

```bash
git status
```
Expected: `.gitignore` modified, `static/version.js` deleted (from index only), no untracked files.

- [ ] **Step 5: Commit**

```bash
git add .gitignore
git commit -m "build: remove version.js from git, generate at deploy time"
```

---

### Task 2: Add version-age.js fallback for missing APP_VERSION

**Files:**
- Modify: `static/version-age.js:23-31`

- [ ] **Step 1: Update renderDeployAge to show "dev" when APP_VERSION is undefined**

In `static/version-age.js`, the `renderDeployAge` function (line 23), change the fallback:

```javascript
// Current (line 28-29):
    if (!parsed) {
      el.textContent = window.APP_VERSION || '';
      return;
    }

// New:
    if (!parsed) {
      el.textContent = window.APP_VERSION || 'dev';
      return;
    }
```

- [ ] **Step 2: Verify locally**

Open `http://localhost:8000/` — the version tag in the bottom-right should show "dev".

- [ ] **Step 3: Commit**

```bash
git add static/version-age.js
git commit -m "fix: show 'dev' in version tag when APP_VERSION is missing"
```

---

### Task 3: Create GitHub Action for deploy-info.json

**Files:**
- Create: `.github/workflows/deploy-info.yml`

- [ ] **Step 1: Create the workflow file**

```yaml
name: Deploy Info

on:
  push:
    branches: [master]

permissions:
  contents: write

jobs:
  deploy-info:
    runs-on: ubuntu-latest
    if: github.actor != 'github-actions[bot]'

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # full history for git log

      - name: Compute changelog
        id: changelog
        run: |
          PREV_SHA=""
          if [ -f static/deploy-info.json ]; then
            PREV_SHA=$(python3 -c "import json; print(json.load(open('static/deploy-info.json'))['sha'])" 2>/dev/null || true)
          fi

          if [ -n "$PREV_SHA" ] && git cat-file -e "$PREV_SHA" 2>/dev/null; then
            # Get commits since last deploy, exclude bot commits
            CHANGELOG=$(git log --oneline "$PREV_SHA"..HEAD \
              --no-merges \
              --author-date-order \
              --invert-grep --grep="chore: update deploy-info" \
              --format="%s" | head -20)
          else
            # First run or SHA not in history — use HEAD commit only
            CHANGELOG=$(git log -1 --format="%s" HEAD)
          fi

          # Write JSON safely (avoids shell injection from commit messages)
          SHA=$(git rev-parse HEAD)
          TIMESTAMP=$(date -u '+%Y-%m-%d %H:%M')

          export CHANGELOG SHA TIMESTAMP
          python3 << 'PYEOF'
          import json, os

          changelog = [l for l in os.environ["CHANGELOG"].strip().split("\n") if l]
          data = {
              "sha": os.environ["SHA"],
              "timestamp": os.environ["TIMESTAMP"],
              "changelog": changelog,
          }
          json.dump(data, open("static/deploy-info.json", "w"), indent=2)
          print(json.dumps(data, indent=2))
          PYEOF

      - name: Commit and push
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add -f static/deploy-info.json
          if git diff --cached --quiet; then
            echo "No changes to deploy-info.json"
            exit 0
          fi
          git commit -m "chore: update deploy-info [skip ci]"
          git push
```

- [ ] **Step 2: Verify the workflow YAML is valid**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/deploy-info.yml'))" 2>/dev/null || echo "Install pyyaml to validate"
```

Or just verify it's valid YAML by checking indentation is correct.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/deploy-info.yml
git commit -m "ci: add GitHub Action to generate deploy-info.json on push to master"
```

---

### Task 4: Update watch-deploy.sh with multi-commit changelog

**Files:**
- Modify: `watch-deploy.sh:54-57` (replace `get_commit_message`)
- Modify: `watch-deploy.sh:241` (call new function)
- Modify: `watch-deploy.sh:89-113` (notification truncation)

- [ ] **Step 1: Replace get_commit_message with get_changelog**

In `watch-deploy.sh`, replace the `get_commit_message` function (lines 54-57):

```bash
# Old:
get_commit_message() {
  local sha="$1"
  gh api "repos/$REPO/commits/$sha" --jq '.commit.message' 2>/dev/null | head -1
}

# New:
get_changelog() {
  local old_sha="$1"
  local new_sha="$2"
  local raw
  raw=$(gh api "repos/$REPO/compare/${old_sha}...${new_sha}" \
    --jq '[.commits[].commit.message | split("\n")[0]] | reverse | join("\n")' 2>/dev/null)
  if [ -z "$raw" ]; then
    # Fallback: single commit message
    gh api "repos/$REPO/commits/$new_sha" --jq '.commit.message' 2>/dev/null | head -1
    return
  fi
  # Filter out bot commits
  echo "$raw" | grep -v "^chore: update deploy-info"
}
```

- [ ] **Step 2: Add truncation helper for notifications**

Add after `get_changelog`:

```bash
truncate_changelog() {
  local changelog="$1"
  local max_lines="${2:-3}"
  local total
  total=$(echo "$changelog" | wc -l | tr -d ' ')
  if [ "$total" -le "$max_lines" ]; then
    echo "$changelog"
  else
    echo "$changelog" | head -n "$max_lines"
    echo "... +$((total - max_lines)) more"
  fi
}
```

- [ ] **Step 3: Update merge detection to use get_changelog**

In the merge detection block (line 241), replace the single occurrence:
```bash
# Old:
COMMIT_MSG=$(get_commit_message "$CURRENT_HEAD")
```
with:
```bash
# New:
COMMIT_MSG=$(get_changelog "$LAST_MASTER_HEAD" "$CURRENT_HEAD")
```

Note: There is only one call to `get_commit_message` in the file (line 241). The overlapping-push case (~line 254) reuses the same `COMMIT_MSG` and does not call `get_commit_message` again — no change needed there.

`LAST_MASTER_HEAD` holds the previous SHA before it's updated on line 242, so the comparison range is correct. Changelog is returned newest-first.

- [ ] **Step 4: Update notification functions for truncation**

In `notify_countdown` (~line 113), change:
```bash
terminal-notifier -title "$title" -message "$COMMIT_MSG" -group deploy &>/dev/null &
```
to:
```bash
terminal-notifier -title "$title" -message "$(truncate_changelog "$COMMIT_MSG" 3)" -group deploy &>/dev/null &
```

In `notify_success` (~line 119), change:
```bash
terminal-notifier -title "🚀 Deployed!" -message "$COMMIT_MSG" -group deploy -timeout 5 &
```
to:
```bash
terminal-notifier -title "🚀 Deployed!" -message "$(truncate_changelog "$COMMIT_MSG" 5)" -group deploy -timeout 5 &
```

- [ ] **Step 5: Suppress no-op deploys (bot-only commits)**

After computing `COMMIT_MSG` in the merge detection block, add a guard:

```bash
# Skip if changelog is empty (only bot commits)
if [ -z "$(echo "$COMMIT_MSG" | tr -d '[:space:]')" ]; then
  echo "$(date '+%H:%M:%S') ⏭️  Skipping bot-only deploy (no human commits)"
  LAST_MASTER_HEAD="$CURRENT_HEAD"
  continue
fi
```

- [ ] **Step 6: Test locally**

```bash
# Simulate what get_changelog returns
gh api "repos/victorrentea/training-assistant/compare/HEAD~3...HEAD" \
  --jq '[.commits[].commit.message | split("\n")[0]] | reverse | join("\n")'
```

Expected: 3 commit subjects, most recent first.

- [ ] **Step 7: Commit**

```bash
git add watch-deploy.sh
git commit -m "feat: show multi-commit changelog in deploy notifications"
```

---

### Task 5: Update CLAUDE.md — remove stale pre-commit hook reference

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update versioning documentation**

In `CLAUDE.md`, find the line about pre-commit hook:
```
- **Versioning**: a pre-commit git hook stamps `static/version.js` with the current timestamp; both host and participant pages display it in the bottom-right corner
```

Replace with:
```
- **Versioning**: `static/version.js` is generated at Railway deploy time (not committed to git); a GitHub Action generates `static/deploy-info.json` with changelog on each push to master; both host and participant pages display the version age in the bottom-right corner
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md versioning section for deploy-time generation"
```

---

### Task 6: Document Railway start command change

**Files:**
- Create: `docs/superpowers/specs/railway-start-command.md` (reference doc)

- [ ] **Step 1: Create a reference document for the Railway dashboard change**

This is a manual step that cannot be automated. Create a note:

```markdown
# Railway Start Command (Manual Step)

Update the Railway dashboard start command to:

```
echo "window.APP_VERSION = '$(date -u '+%Y-%m-%d %H:%M')';" > static/version.js && uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
```

This generates `static/version.js` at deploy time with the current UTC timestamp.

Previous command (if any): `uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}`
```

- [ ] **Step 2: Remind user to update Railway dashboard**

Print a reminder that the Railway dashboard start command must be updated manually.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/railway-start-command.md
git commit -m "docs: add Railway start command reference for manual update"
```
