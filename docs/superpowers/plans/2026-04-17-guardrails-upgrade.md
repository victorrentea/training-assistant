1# Guardrails Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add defense-in-depth guardrails: pyright type checking, ruff/shellcheck/gitleaks in CI, gitleaks in pre-commit hook, and a Claude Code pre-commit checklist skill.

**Architecture:** Four independent changes land in sequence — pyproject/config first (pyright setup), then CI YAML (lint job), then the git hook (gitleaks layer), then the skill + Claude Code settings hook. Each is independently committable and verifiable.

**Tech Stack:** pyright (type checking), ruff (lint, already installed), shellcheck (shell lint, system tool), gitleaks (secret scanning, GitHub Action + optional local), Claude Code skills + settings hooks.

---

## Files Touched

| File | Action |
|---|---|
| `pyproject.toml` | Add `pyright>=1.1` to `dev` extras |
| `pyrightconfig.json` | Create — basic type-check config |
| `.github/workflows/ci.yml` | Add `lint` job |
| `hooks/pre-commit` | Add gitleaks check after existing secret scanner |
| `~/workspace/ai/skills/pre-commit-checklist/SKILL.md` | Create — rigid pre-commit checklist skill |
| `.claude/settings.json` | Add `PreToolUse` hook for git commit reminder |

---

## Task 1: Add Pyright to Dev Extras + Create Config

**Files:**
- Modify: `pyproject.toml`
- Create: `pyrightconfig.json`

- [ ] **Step 1: Add pyright to dev extras in pyproject.toml**

In `pyproject.toml`, change the `dev` extras block from:
```toml
dev = [
    "pytest>=8.0",
    "pytest-bdd>=8.0",
    "httpx>=0.28",
    "requests>=2.32",
    "import-linter>=2.5",
    "vulture>=2.14",
    "ruff>=0.6",
]
```
to:
```toml
dev = [
    "pytest>=8.0",
    "pytest-bdd>=8.0",
    "httpx>=0.28",
    "requests>=2.32",
    "import-linter>=2.5",
    "vulture>=2.14",
    "ruff>=0.6",
    "pyright>=1.1",
]
```

- [ ] **Step 2: Create pyrightconfig.json at repo root**

Create `/Users/victorrentea/workspace/training-assistant/pyrightconfig.json`:
```json
{
  "typeCheckingMode": "basic",
  "pythonVersion": "3.12",
  "include": ["railway", "daemon"],
  "exclude": ["tests", "scripts"]
}
```

`basic` mode — does not require full type annotations; only flags clear type errors.

- [ ] **Step 3: Install and verify pyright is available**

```bash
uv sync --extra dev
uv run --extra dev pyright --version
```

Expected output: `pyright 1.x.x`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml pyrightconfig.json
git commit -m "build: add pyright to dev extras with basic-mode config"
```

---

## Task 2: Fix Pyright Errors

**Files:** Various `railway/` and `daemon/` Python files (scope unknown until run)

- [ ] **Step 1: Run pyright and capture output**

```bash
uv run --extra dev pyright 2>&1 | tee /tmp/pyright-errors.txt
tail -5 /tmp/pyright-errors.txt
```

The last line shows the error summary, e.g. `Found 23 errors in 8 files`.

- [ ] **Step 2: Fix all reported errors**

Work through `/tmp/pyright-errors.txt` top to bottom. Common patterns and fixes:

**"Cannot access attribute X on type None"** — add a None guard:
```python
# before
result = obj.method()
# after
if obj is not None:
    result = obj.method()
```

**"Argument of type X is not assignable to parameter of type Y"** — add explicit cast or fix the type:
```python
# before
items: list[str] = some_func()  # returns list[Any]
# after
items: list[str] = list(some_func())
```

**"Type of X is partially unknown"** — add a type annotation:
```python
# before
data = {}
# after
data: dict[str, str] = {}
```

**"Return type is not compatible"** — match the declared return type or remove the annotation if it was wrong.

If an error is a genuine false positive (e.g., dynamic attribute set via `setattr`), suppress it inline:
```python
result = some_dynamic_call()  # type: ignore[assignment]
```
Use `# type: ignore` sparingly — prefer fixing the root cause.

- [ ] **Step 3: Re-run pyright until clean**

```bash
uv run --extra dev pyright 2>&1 | tail -5
```

Expected: `0 errors in N files`

- [ ] **Step 4: Commit**

```bash
git add -u
git commit -m "fix: resolve pyright basic-mode type errors in railway and daemon"
```

---

## Task 3: Add Lint CI Job

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Add `lint` job to ci.yml**

In `.github/workflows/ci.yml`, append the following **after** the `hermetic` job (at the end of the file). The `lint` job has no `needs:` — it runs in parallel with `checks`:

```yaml
  lint:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install lint tools
        run: pip install ruff pyright

      - name: Ruff — lint all Python
        run: ruff check .

      - name: Pyright — type check
        run: pyright

      - name: Shellcheck — lint shell scripts
        run: |
          sudo apt-get install -y shellcheck
          git ls-files '*.sh' | xargs shellcheck

      - name: Gitleaks — secret scan
        uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

- [ ] **Step 2: Verify the YAML is syntactically valid**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo "YAML OK"
```

Expected: `YAML OK`

- [ ] **Step 3: Commit and push — verify CI passes**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add lint job (ruff, pyright, shellcheck, gitleaks)"
git push --no-verify
```

Then watch GitHub Actions. The `lint` job must go green. If shellcheck flags issues, fix them (Task 3a below) before declaring this task done.

**If shellcheck fails:** Common fixes:
- `SC2086` (word splitting): quote variables — `"$VAR"` instead of `$VAR`
- `SC2046` (word splitting in command substitution): use array — `mapfile -t files < <(git ls-files '*.sh')`
- `SC2034` (unused variable): prefix with `_` or remove

Fix the shell script, re-commit, re-push with `--no-verify`.

---

## Task 4: Add Gitleaks to Pre-commit Hook

**Files:**
- Modify: `hooks/pre-commit`

- [ ] **Step 1: Install gitleaks locally**

```bash
brew install gitleaks
gitleaks version
```

Expected: `v8.x.x`

- [ ] **Step 2: Add gitleaks check after the custom secret scanner block**

In `hooks/pre-commit`, the custom scanner block ends at line 27 (`fi`). Add the gitleaks check immediately after that `fi`, before the `stage_index_sequence_svgs` function definition:

```sh
if command -v gitleaks >/dev/null 2>&1; then
  gitleaks protect --staged --no-banner 2>&1 || {
    echo "ERROR: Gitleaks detected potential secrets in staged changes. Aborting." >&2
    exit 1
  }
fi
```

The full updated top of `hooks/pre-commit` should look like:
```sh
#!/bin/sh

# Regenerate maintained generated docs, stage them, and block secret leaks.

set -eu

REPO_ROOT="$(git rev-parse --show-toplevel)"

# Block commits that contain secret values from secrets.env
SECRETS_FILE="$REPO_ROOT/secrets.env"
if [ -f "$SECRETS_FILE" ]; then
  staged_diff="$(git diff --cached --diff-filter=ACMR -U0 -- . ':!secrets.env' ':!*.svg' || true)"
  if [ -n "$staged_diff" ]; then
    while IFS='=' read -r key value; do
      # Skip comments and empty lines
      case "$key" in
        '#'*|'') continue ;;
      esac
      [ -n "$value" ] || continue
      # Skip values shorter than 6 chars — too noisy (e.g. "host" matches filenames)
      [ "${#value}" -ge 6 ] || continue
      if printf '%s\n' "$staged_diff" | grep -qF "$value"; then
        echo "ERROR: Secret value for $key found in staged changes. Aborting commit." >&2
        exit 1
      fi
    done < "$SECRETS_FILE"
  fi
fi

if command -v gitleaks >/dev/null 2>&1; then
  gitleaks protect --staged --no-banner 2>&1 || {
    echo "ERROR: Gitleaks detected potential secrets in staged changes. Aborting." >&2
    exit 1
  }
fi

stage_index_sequence_svgs() {
```

- [ ] **Step 3: Verify the hook runs cleanly on a test commit**

Stage any small change (e.g., add a comment to a Python file), then try committing:

```bash
echo "# test" >> railway/app.py
git add railway/app.py
git commit -m "test: verify pre-commit hook with gitleaks"
```

Expected: commit succeeds; gitleaks outputs nothing (no secrets in staged files). Then revert:

```bash
git revert HEAD --no-edit
```

- [ ] **Step 4: Commit the hook change**

```bash
git add hooks/pre-commit
git commit -m "chore: add gitleaks protect to pre-commit hook (complements custom scanner)"
git push --no-verify
```

---

## Task 5: Write Pre-commit Checklist Skill

**Files:**
- Create: `~/workspace/ai/skills/pre-commit-checklist/SKILL.md`

- [ ] **Step 1: Create the skill directory and file**

```bash
mkdir -p ~/workspace/ai/skills/pre-commit-checklist
```

Write `~/workspace/ai/skills/pre-commit-checklist/SKILL.md` with the following content (use your Write tool or editor — the code fences below use ` ``` ` as-is inside the file):

**Frontmatter:**
```
---
name: pre-commit-checklist
description: Run before every git commit — catches lint, type, dead-code, shell, and secret issues. Rigid skill.
type: rigid
---
```

**Body:** (write each section with real sh code fences)

Section: `# Pre-Commit Checklist` — preamble: "This is a rigid skill. Run ALL steps in order. Do not skip any step."

Section: `## Runner Detection` — shell block:
```sh
if arch -arm64 /usr/bin/true >/dev/null 2>&1; then
  RUNNER="arch -arm64 uv run --extra dev --extra daemon"
else
  RUNNER="uv run --extra dev --extra daemon"
fi
```

Section: `## Changed Files` — shell block:
```sh
CHANGED_PY="$(git diff --name-only --diff-filter=ACMR origin/master...HEAD -- '*.py')"
CHANGED_SH="$(git diff --name-only --diff-filter=ACMR origin/master...HEAD -- '*.sh')"
```

Section: `## Step 1 — Ruff Lint + Auto-fix`:
```sh
if [ -n "$CHANGED_PY" ]; then
  $RUNNER ruff check $CHANGED_PY --fix
fi
```
Text: "Re-run until output is clean. Manually fix any non-auto-fixable errors."

Section: `## Step 2 — Dead Code`:
```sh
$RUNNER python3 -m vulture
```
Text: "Expected: no output. If new dead code is flagged, remove it or add to `vulture_whitelist.py`."

Section: `## Step 3 — Type Checking`:
```sh
if [ -n "$CHANGED_PY" ]; then
  $RUNNER pyright $CHANGED_PY
fi
```
Text: "Fix all type errors before proceeding. Use `# type: ignore[assignment]` only as a last resort."

Section: `## Step 4 — Shell Script Lint`:
```sh
if [ -n "$CHANGED_SH" ]; then
  shellcheck $CHANGED_SH
fi
```

Section: `## Step 5 — Visual Secret Scan` — text: "Run `git diff --cached` and visually scan for passwords, tokens, API keys, UUIDs, or any value that looks like a credential. Pay special attention to strings matching entries in `~/.training-assistants-secrets.env`."

Section: `## Step 6 — API.md Freshness` — text: "If any Pydantic `BaseModel` subclass or FastAPI route decorator (`@router.`) was changed:" then shell block:
```sh
git diff --cached --name-only | grep -q "^API.md$" \
  && echo "API.md staged OK" \
  || echo "WARNING: API.md not staged — run: python3 scripts/generate_apis_md.py --output API.md && git add API.md"
```
Text: "If the warning fires, run the regeneration command and stage the result before committing."

- [ ] **Step 2: Commit and push the skill**

```bash
cd ~/workspace/ai
git add skills/pre-commit-checklist/SKILL.md
git commit -m "feat: add pre-commit-checklist skill for training-assistant"
git push
cd ~/workspace/training-assistant
```

- [ ] **Step 3: Verify the skill is discoverable**

In a Claude Code session, type `/victor-skills:pre-commit-checklist` and confirm the skill loads without error.

---

## Task 6: Add PreToolUse Auto-hook to Claude Code Settings

**Files:**
- Modify: `.claude/settings.json`

- [ ] **Step 1: Add PreToolUse hook to .claude/settings.json**

Current `.claude/settings.json`:
```json
{
  "enabledPlugins": {
    "superpowers@claude-plugins-official": true
  },
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "async": true,
            "statusMessage": "Running tests...",
            "timeout": 120,
            "command": "FILE=$(jq -r '.tool_input.file_path // .tool_response.filePath'); echo \"$FILE\" | grep -qE '\\.(py|js)$' || exit 0; cd /Users/victorrentea/PycharmProjects/training-assistant && python3 -m pytest test_main.py -q 2>&1 | tail -5 && node test_participant_js.js 2>&1 | tail -2 && python3 -m pytest test_e2e.py -q 2>&1 | tail -5"
          }
        ]
      }
    ]
  }
}
```

Replace the entire file with:
```json
{
  "enabledPlugins": {
    "superpowers@claude-plugins-official": true
  },
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "COMMAND=$(jq -r '.tool_input.command // \"\"'); echo \"$COMMAND\" | grep -q 'git commit' || exit 0; echo 'REMINDER: Run /victor-skills:pre-commit-checklist before committing.'"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "async": true,
            "statusMessage": "Running tests...",
            "timeout": 120,
            "command": "FILE=$(jq -r '.tool_input.file_path // .tool_response.filePath'); echo \"$FILE\" | grep -qE '\\.(py|js)$' || exit 0; cd /Users/victorrentea/PycharmProjects/training-assistant && python3 -m pytest test_main.py -q 2>&1 | tail -5 && node test_participant_js.js 2>&1 | tail -2 && python3 -m pytest test_e2e.py -q 2>&1 | tail -5"
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 2: Verify the hook fires**

In the Claude Code session (after settings reload), run any `git commit` command via the Bash tool. Confirm the output includes:

```
REMINDER: Run /victor-skills:pre-commit-checklist before committing.
```

- [ ] **Step 3: Commit**

```bash
git add .claude/settings.json
git commit -m "chore: add PreToolUse hook to remind Claude to run pre-commit-checklist"
git push --no-verify
```
