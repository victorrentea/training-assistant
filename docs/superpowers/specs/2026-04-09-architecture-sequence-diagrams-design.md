# Architecture Sequence Diagram Split and SVG Sync

## Problem

`ARCHITECTURE.md` used to contain a single large PlantUML sequence diagram covering many flows. That diagram is no longer present in the current document, so the sequence-flow view has effectively disappeared. The user wants that interaction view restored, but split into smaller source files that are easier to maintain.

The updated workflow also needs generated SVGs committed in the repo and referenced from `ARCHITECTURE.md`, plus automation so changing any `.puml` updates the matching `.svg`. The important constraint is not just convenience; the repository must also reject stale generated SVGs.

Just as importantly, the diagrams must describe the system as it works today. The old monolith is useful as a coverage inventory, but the new split diagrams must be re-authored from the current code in `daemon/`, `railway/`, and `static/`, not copied forward blindly.

## Goal

- Restore the sequence-flow view in `ARCHITECTURE.md`.
- Split that content into focused `.puml` files under `docs/sequences/`.
- Add a top-level table of contents to `ARCHITECTURE.md`.
- Add titled sequence-diagram sections in `ARCHITECTURE.md` that embed generated SVGs, not raw PlantUML.
- Provide one repository script that can render, watch, and verify the diagrams.
- Enforce `.puml`/`.svg` sync locally before push.
- Reconcile every split diagram with the current implementation before it is committed.

## Source of Truth

The source of truth is the current implementation in:

- `daemon/`
- `railway/`
- `static/`

The old monolithic sequence diagram from `ARCHITECTURE.md` in commit `18dadf10`, under `System Interactions (Sequence Flows)`, is only a recovery aid. It provides a candidate list of flows that previously mattered, but each split diagram must be validated and updated against the current code before being rendered and referenced.

## Diagram Split

Create a new source directory:

```text
docs/sequences/
  01-session-lifecycle-and-recovery.puml
  02-participant-join-and-geolocation.puml
  03-poll-and-quiz.puml
  04-qa-and-wordcloud.puml
  05-code-review-and-debate.puml
  06-slides-cache-and-follow-trainer.puml
  07-participant-to-host-inputs-and-emoji.puml
  08-activity-summary-and-leaderboard.puml
  svg/
    *.svg
```

The eight diagrams map to the old numbered flows like this:

| New file | Covers old flows |
|---|---|
| `01-session-lifecycle-and-recovery.puml` | 1, 18, 19 |
| `02-participant-join-and-geolocation.puml` | 2 |
| `03-poll-and-quiz.puml` | 3 |
| `04-qa-and-wordcloud.puml` | 4, 5 |
| `05-code-review-and-debate.puml` | 6, 7 |
| `06-slides-cache-and-follow-trainer.puml` | 8, 9, 10 |
| `07-participant-to-host-inputs-and-emoji.puml` | 11, 12, 13 |
| `08-activity-summary-and-leaderboard.puml` | 14, 15, 16, 17 |

This is the recommended split because it keeps each diagram readable while preserving coverage of the previously documented flows. One file per original flow would be mechanically simple but would make `ARCHITECTURE.md` too fragmented.

The mapping is a starting point, not a freeze on historical behavior. During implementation, each diagram must be corrected to match the current architecture. If one of the old numbered flows no longer exists or has materially changed shape, the split diagram should reflect the current behavior and note the updated scope in `ARCHITECTURE.md`.

## ARCHITECTURE.md Structure

`ARCHITECTURE.md` will gain a table of contents near the top, immediately after the introductory block. The TOC should include the current high-level sections plus the new sequence-diagram subsections.

Expected sequence-diagram headings:

- `## Sequence Diagrams`
- `### Session Lifecycle and Recovery`
- `### Participant Join and Geolocation`
- `### Poll and Quiz`
- `### Q&A and Word Cloud`
- `### Code Review and Debate`
- `### Slides Cache and Follow Trainer`
- `### Participant-to-Host Inputs and Emoji`
- `### Activity, Summary, and Leaderboard`

Each subsection will contain:

1. A one-sentence summary of what the diagram covers.
2. The current code path or behavior family it corresponds to, with optional mention of the legacy flow numbers when that mapping is still useful.
3. A markdown image reference to the generated SVG, for example:

```md
![Session lifecycle and recovery](docs/sequences/svg/01-session-lifecycle-and-recovery.svg)
```

The current C4 sections stay inline and unchanged for now. This change is only for the split sequence-flow content, and those sections must reference generated SVGs rather than embedding raw PlantUML blocks.

## Rendering Script

Add a new script:

```text
scripts/render_puml_svgs.py
```

The script will use the native `plantuml` CLI already available in the development environment and call it through `subprocess`.

Required modes:

### Default render mode

- Render all `.puml` files under `docs/sequences/` when no paths are passed.
- If one or more `.puml` paths are passed, render only those files.
- Write outputs to `docs/sequences/svg/<stem>.svg`.
- Create the `svg/` directory if missing.

### `--watch`

- Poll `docs/sequences/*.puml` for content or mtime changes every second.
- Re-render only changed files.
- Print one concise line per regenerated SVG.

This is convenience automation for active editing.

### `--check`

- Render the target `.puml` files into a temporary directory.
- Compare each generated SVG byte-for-byte with the committed SVG in `docs/sequences/svg/`.
- Fail with exit code `1` if any SVG is missing or differs.
- Print the stale or missing file paths.

This is the enforcement mode.

## Why Check Mode Is the Real Sync Guard

Timestamps alone are not enough. Git clones, rebases, and merges change mtimes, so “SVG newer than PUML” is not a trustworthy signal. The reliable rule is: re-render and compare the actual SVG bytes.

That means sync is guaranteed by:

1. Auto-rendering on local changes for convenience.
2. A deterministic `--check` mode that re-renders and fails on differences.

The watch loop is helpful, but it is not the source of enforcement.

## Hook Integration

### Pre-commit

Extend `hooks/pre-commit` so it also handles sequence diagrams:

- If staged files include `docs/sequences/*.puml`, run `python3 scripts/render_puml_svgs.py` on those files and `git add` the matching SVGs.
- If staged files include `scripts/render_puml_svgs.py`, run the renderer for all sequence diagrams and stage all `docs/sequences/svg/*.svg`.

This keeps commits self-healing for normal development.

### Pre-push

Extend `hooks/pre-push` to run:

```bash
python3 scripts/render_puml_svgs.py --check
```

This is what actually blocks stale SVGs from reaching `master`.

If the repository later adds CI for documentation checks, CI should run the same `--check` command. That is optional for this change; the repo already relies heavily on local hooks.

## Tooling Assumptions

The current environment already has:

- `plantuml`
- `java`
- `dot`

The renderer script should still validate that `plantuml` exists on `PATH` and fail with a short actionable error if not.

No new Python dependency is required. The watch mode will use a simple polling loop from the standard library instead of adding `watchdog`.

## Out of Scope

- Converting the current inline C4 diagrams to SVG files.
- Changing the semantics of the recovered sequence flows.
- Auto-editing diagrams from code analysis.
- Server-side or GitHub Action enforcement beyond the existing local hook workflow.

## Verification Plan

Implementation should prove the workflow with:

1. `python3 scripts/render_puml_svgs.py`
2. `python3 scripts/render_puml_svgs.py --check`
3. `sh -n hooks/pre-commit`
4. `sh -n hooks/pre-push`
5. `git diff --check`
6. Targeted code-to-doc verification for each sequence diagram by inspecting the live code paths it claims to describe

The resulting `ARCHITECTURE.md` should show a visible TOC and embed all generated SVGs from `docs/sequences/svg/`.
