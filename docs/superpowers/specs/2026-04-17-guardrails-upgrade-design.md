# Guardrails Upgrade Design

**Date:** 2026-04-17  
**Inspired by:** [microservices.io GenAI Development Platform — Part 1](https://microservices.io/post/architecture/2026/03/09/genai-development-platform-part-1-development-guardrails.html)

## Goal

Strengthen the project's quality enforcement stack with defense-in-depth guardrails, closing gaps where `--no-verify` bypasses local hooks and where no static type checking exists. Inspired by the article's layered approach: instruction-based skill → deterministic hooks → CI → automated PR review.

---

## Current State

| Layer | What exists |
|---|---|
| Pre-commit hook | Custom secret scan (reads `secrets.env`), API.md regen, SVG rendering |
| Pre-push hook | `check-all.sh` (tests + contracts + architecture), ruff on changed files, vulture |
| CI | Unit + E2E + hermetic tests — **no lint, no type checking** |
| PR review | Claude automated review via `claude-review.yml` |

**Key gap:** `--no-verify` bypasses all local hooks. CI has no lint or type-checking backstop.

---

## Design

### 1. CI — New `lint` Job

Add a `lint` job to `.github/workflows/ci.yml` that runs **in parallel** with the existing `checks` job (no dependency between them — fast feedback).

Steps:

| Step | Command | Notes |
|---|---|---|
| Ruff | `ruff check .` | All Python files, not just changed ones |
| Pyright | `pyright` | Basic type checking mode |
| Shellcheck | `shellcheck $(git ls-files '*.sh')` | All shell scripts |
| Gitleaks | `gitleaks/gitleaks-action` | Official GitHub Action, catches secrets |

Install for CI: `pip install ruff pyright vulture` (ruff and vulture already in dev extras; pyright added).

### 2. Pyright Configuration

Add `pyrightconfig.json` at repo root:

```json
{
  "typeCheckingMode": "basic",
  "pythonVersion": "3.12",
  "include": ["railway", "daemon"],
  "exclude": ["tests", "scripts"]
}
```

`basic` mode avoids flooding errors on a codebase with no prior type annotations. Can be tightened over time.

Add `pyright>=1.1` to `dev` extras in `pyproject.toml`.

### 3. Gitleaks Complements (Does Not Replace) the Custom Secret Scanner

The two scanners are complementary, not redundant:

- **Custom scanner** (`secrets.env` loop): catches this project's own known secrets by value — precise, zero false negatives for project credentials
- **Gitleaks**: catches real-world secret patterns (API keys, tokens, private keys) that weren't in `secrets.env` — broad coverage for accidental leaks

**Change:** Keep the custom secret-scan block in `hooks/pre-commit` unchanged. Add Gitleaks **after** it:

```sh
if command -v gitleaks >/dev/null 2>&1; then
  gitleaks protect --staged --no-banner 2>&1 || {
    echo "ERROR: Gitleaks detected potential secrets in staged changes. Aborting." >&2
    exit 1
  }
fi
```

The `command -v` guard makes it optional locally (`brew install gitleaks` to enable). The CI Gitleaks action (Section 1) is the mandatory backstop.

The rest of `hooks/pre-commit` (API.md regen, SVG rendering) is unchanged.

### 4. Pre-commit Checklist Skill

New skill: `victor-skills:pre-commit-checklist`  
Location: `~/workspace/ai/skills/pre-commit-checklist/SKILL.md`

**Checklist** (rigid — follow all steps, do not skip):

1. `uv run --extra dev ruff check <changed .py files> --fix` — lint and auto-fix
2. `uv run --extra dev python3 -m vulture` — no dead code introduced
3. `uv run --extra dev pyright <changed .py files>` — no new type errors
4. `shellcheck <changed .sh files>` — no shell script issues
5. Visual scan of staged diff for obvious secrets
6. If any Pydantic models or FastAPI routes changed: confirm `API.md` is up to date (pre-commit hook regenerates it, but verify it's staged)

**Runner pattern:** Use `arch -arm64 uv run --extra dev --extra daemon` on Apple Silicon, `uv run --extra dev --extra daemon` elsewhere — same as `hooks/pre-push`.

### 5. Auto-hook in Claude Code Settings

Add a `PreToolUse` hook in `.claude/settings.json` that fires when Claude Code runs `git commit`, prompting it to invoke `victor-skills:pre-commit-checklist` first.

Add to the `hooks` section in `.claude/settings.json`:

```json
{
  "matcher": "Bash",
  "hooks": [
    {
      "type": "command",
      "command": "COMMAND=$(jq -r '.tool_input.command // \"\"'); echo \"$COMMAND\" | grep -q 'git commit' || exit 0; echo 'REMINDER: Run /victor-skills:pre-commit-checklist before committing.'"
    }
  ]
}
```

This fires on every `Bash` tool call, checks if the command contains `git commit`, and if so prints a reminder. The matcher uses the same `jq`-based `tool_input` access pattern as the existing `Edit|Write` hook in this project.

---

## Rollout Order

1. Add `pyright` to `pyproject.toml` dev extras
2. Add `pyrightconfig.json`
3. Fix any pyright errors surfaced on first run
4. Add `lint` job to CI
5. Replace custom secret scanner with `gitleaks protect --staged` in pre-commit hook
6. Write and commit the pre-commit checklist skill
7. Add the Claude Code auto-hook to `.claude/settings.json`

---

## What This Gives Us

| Before | After |
|---|---|
| `--no-verify` bypasses all quality checks | CI lint job catches ruff/pyright/shellcheck/secrets on every push |
| No static type checking | Pyright basic mode on Railway + daemon code |
| Custom scanner catches project secrets; no broad pattern coverage | Custom scanner kept + Gitleaks layered on top for real-world secret patterns |
| Agent self-discipline: none | Pre-commit checklist skill + auto-hook nudge |
