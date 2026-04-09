import os
import subprocess
from pathlib import Path

import scripts.render_puml_svgs as renderer

ROOT = Path(__file__).resolve().parents[2]
SEQUENCES_DIR = ROOT / "docs" / "sequences"
SVG_DIR = SEQUENCES_DIR / "svg"
ARCHITECTURE_MD = ROOT / "ARCHITECTURE.md"
PRE_COMMIT_HOOK = ROOT / "hooks" / "pre-commit"
PRE_PUSH_HOOK = ROOT / "hooks" / "pre-push"
EXPECTED_SEQUENCE_STEMS = [
    "01-session-lifecycle-and-recovery",
    "02-participant-join-and-geolocation",
    "03-poll-and-quiz",
    "04-qa-and-wordcloud",
    "05-code-review-and-debate",
    "06-slides-cache-and-follow-trainer",
    "07-participant-to-host-inputs-and-emoji",
    "08-activity-summary-and-leaderboard",
]
EXPECTED_SEQUENCE_TITLES = [
    "Session Lifecycle and Recovery",
    "Participant Join and Geolocation",
    "Poll and Quiz",
    "Q&A and Word Cloud",
    "Code Review and Debate",
    "Slides Cache and Follow Trainer",
    "Participant-to-Host Inputs and Emoji",
    "Activity, Summary, and Leaderboard",
]
EXPECTED_SEQUENCE_SUMMARIES = [
    "This diagram covers the daemon-first session start, folder resume, disk restore, and Railway reconnect path for the active `session_id`.",
    "This diagram covers UUID-based participant registration, session-scoped state bootstrap, presence updates, and optional location sharing back to the host view.",
    "This diagram covers Claude-backed quiz draft generation plus the live poll lifecycle from host draft/open through participant votes, close, and score reveal.",
    "This diagram covers participant word submissions, anonymous question and upvote flows, host moderation, and the score updates emitted alongside those actions.",
    "This diagram covers host-launched code review and debate activities, participant submissions, scoring, and the Claude cleanup step that now only applies to debate arguments.",
    "This diagram covers slide catalog loading, Railway PDF cache fill and refresh, and the live follow-trainer flow driven by PowerPoint events from the local addons bridge.",
    "This diagram covers participant paste and feedback actions, Railway-to-daemon upload handoff, and best-effort emoji delivery to both the host UI and desktop overlay.",
    "This diagram covers activity switching, file-backed notes and summary publication, participant state refreshes, and host-controlled leaderboard reveal and hide.",
]


def _run_repo(
    repo: Path,
    args: list[str],
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=repo, env=env, check=False, capture_output=True, text=True)


def _run_repo_ok(repo: Path, args: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    result = _run_repo(repo, args, env=env)
    assert result.returncode == 0, result.stderr or result.stdout
    return result


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _sequence_source_text(label: str) -> str:
    return f"@startuml\nA -> B : {label}\n@enduml\n"


def _sequence_svg_text(path: Path) -> str:
    return f"<svg>{path.read_text(encoding='utf-8')}</svg>\n"


def _write_sequence_source(path: Path, label: str) -> None:
    _write_text(path, _sequence_source_text(label))


def _write_matching_svg(source: Path, svg_path: Path) -> None:
    _write_text(svg_path, _sequence_svg_text(source))


def _write_fake_plantuml(bin_dir: Path) -> None:
    _write_text(
        bin_dir / "plantuml",
        """#!/usr/bin/env python3
import sys
from pathlib import Path

output_dir = Path(sys.argv[sys.argv.index("-o") + 1])
source = Path(sys.argv[-1])
output_dir.mkdir(parents=True, exist_ok=True)
(output_dir / f"{source.stem}.svg").write_text(
    f"<svg>{source.read_text(encoding='utf-8')}</svg>\\n",
    encoding="utf-8",
)
""",
    )
    (bin_dir / "plantuml").chmod(0o755)


def _write_failing_uv(bin_dir: Path) -> None:
    _write_text(
        bin_dir / "uv",
        "#!/bin/sh\n"
        "echo 'uv should not run' >&2\n"
        "exit 99\n",
    )
    (bin_dir / "uv").chmod(0o755)


def _create_hook_test_repo(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    repo = tmp_path / "repo"
    _write_text(repo / "hooks" / "pre-commit", PRE_COMMIT_HOOK.read_text(encoding="utf-8"))
    _write_text(repo / "hooks" / "pre-push", PRE_PUSH_HOOK.read_text(encoding="utf-8"))
    _write_text(
        repo / "scripts" / "render_puml_svgs.py",
        (ROOT / "scripts" / "render_puml_svgs.py").read_text(encoding="utf-8"),
    )
    _write_text(
        repo / "scripts" / "generate_apis_md.py",
        """#!/usr/bin/env python3
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--output", required=True)
args = parser.parse_args()
Path(args.output).write_text("# API\\n", encoding="utf-8")
""",
    )
    _write_text(repo / "API.md", "# API\n")
    _write_text(repo / "DB.md", "# DB\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    _write_fake_plantuml(bin_dir)
    _write_failing_uv(bin_dir)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    _run_repo_ok(repo, ["git", "init"])
    _run_repo_ok(repo, ["git", "config", "user.name", "Hook Tests"])
    _run_repo_ok(repo, ["git", "config", "user.email", "hook-tests@example.com"])
    return repo, env


def _commit_all(repo: Path) -> None:
    _run_repo_ok(repo, ["git", "add", "."])
    _run_repo_ok(repo, ["git", "commit", "-m", "initial"])


def _seed_sequence_repo(tmp_path: Path, stem: str = "01-a", label: str = "first") -> tuple[Path, dict[str, str]]:
    repo, env = _create_hook_test_repo(tmp_path)
    source = repo / "docs" / "sequences" / f"{stem}.puml"
    svg = repo / "docs" / "sequences" / "svg" / f"{stem}.svg"
    _write_sequence_source(source, label)
    _write_matching_svg(source, svg)
    _commit_all(repo)
    return repo, env


def _seed_two_sequence_repo(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    repo, env = _create_hook_test_repo(tmp_path)
    for stem, label in [("01-a", "first"), ("02-b", "second")]:
        source = repo / "docs" / "sequences" / f"{stem}.puml"
        svg = repo / "docs" / "sequences" / "svg" / f"{stem}.svg"
        _write_sequence_source(source, label)
        _write_matching_svg(source, svg)
    _commit_all(repo)
    return repo, env


def _section_lines(text: str, heading: str) -> list[str]:
    lines = text.splitlines()
    start = lines.index(heading)
    end = len(lines)

    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break

    return lines[start:end]


def _sequence_subsections(section_lines: list[str]) -> list[tuple[str, list[str]]]:
    subsections: list[tuple[str, list[str]]] = []
    current_title: str | None = None
    current_lines: list[str] = []

    for line in section_lines[1:]:
        if line.startswith("### "):
            if current_title is not None:
                subsections.append((current_title, current_lines))
            current_title = line.removeprefix("### ")
            current_lines = []
            continue

        if current_title is not None:
            current_lines.append(line)

    if current_title is not None:
        subsections.append((current_title, current_lines))

    return subsections


def _sorted_stems(directory: Path, suffix: str) -> list[str]:
    return sorted(path.stem for path in directory.glob(f"*{suffix}"))


def _expected_sequence_sources() -> list[Path]:
    return [SEQUENCES_DIR / f"{stem}.puml" for stem in EXPECTED_SEQUENCE_STEMS]


def test_expected_sequence_source_files_exist():
    assert _sorted_stems(SEQUENCES_DIR, ".puml") == EXPECTED_SEQUENCE_STEMS


def test_expected_sequence_svg_files_exist():
    assert _sorted_stems(SVG_DIR, ".svg") == EXPECTED_SEQUENCE_STEMS


def test_expected_sequence_svgs_are_in_sync():
    assert renderer.check_render_sync(_expected_sequence_sources(), SVG_DIR) == []


def test_pre_commit_hook_renders_and_stages_sequence_svgs():
    text = PRE_COMMIT_HOOK.read_text(encoding="utf-8")

    assert 'python3 "$REPO_ROOT/scripts/generate_apis_md.py" --output "$REPO_ROOT/API.md" >/dev/null' in text
    assert 'git add "$REPO_ROOT/API.md" "$REPO_ROOT/DB.md"' in text
    assert "git diff --cached --name-only --diff-filter=ACMR -- scripts/render_puml_svgs.py" in text
    assert "git diff --cached --name-only --diff-filter=ACMRD -- 'docs/sequences/*.puml'" in text
    assert 'stage_index_sequence_svgs() {' in text
    assert "git ls-files --cached -- 'docs/sequences/*.puml'" in text
    assert 'git show ":$path" > "$tmp_path"' in text
    assert "git diff --cached --name-status --find-renames --diff-filter=DR -- 'docs/sequences/*.puml'" in text
    assert 'git add -A -- "$old_svg"' in text
    assert "stage_index_sequence_svgs all" in text
    assert "stage_index_sequence_svgs staged" in text


def test_pre_push_hook_checks_rendered_sequence_svgs():
    text = PRE_PUSH_HOOK.read_text(encoding="utf-8")

    assert 'python3 "$REPO_ROOT/scripts/render_puml_svgs.py" --check' in text
    assert '$RUNNER bash "$REPO_ROOT/tests/check-all.sh"' in text
    assert '$RUNNER python3 -m vulture' in text


def test_pre_commit_hook_stages_svg_deletion_for_staged_source_delete(tmp_path):
    repo, env = _seed_sequence_repo(tmp_path)
    svg = repo / "docs" / "sequences" / "svg" / "01-a.svg"

    _run_repo_ok(repo, ["git", "rm", "docs/sequences/01-a.puml"])

    result = _run_repo(repo, ["sh", "hooks/pre-commit"], env=env)

    assert result.returncode == 0, result.stderr or result.stdout
    assert not svg.exists()
    assert _run_repo_ok(
        repo,
        ["git", "diff", "--cached", "--name-status", "--", "docs/sequences/svg"],
    ).stdout.splitlines() == ["D\tdocs/sequences/svg/01-a.svg"]


def test_pre_commit_hook_replaces_svg_for_staged_source_rename(tmp_path):
    repo, env = _seed_sequence_repo(tmp_path)
    old_svg = repo / "docs" / "sequences" / "svg" / "01-a.svg"
    new_source = repo / "docs" / "sequences" / "02-b.puml"
    new_svg = repo / "docs" / "sequences" / "svg" / "02-b.svg"

    _run_repo_ok(repo, ["git", "mv", "docs/sequences/01-a.puml", "docs/sequences/02-b.puml"])

    result = _run_repo(repo, ["sh", "hooks/pre-commit"], env=env)

    assert result.returncode == 0, result.stderr or result.stdout
    assert not old_svg.exists()
    assert new_svg.read_text(encoding="utf-8") == _sequence_svg_text(new_source)
    svg_status = _run_repo_ok(
        repo,
        ["git", "diff", "--cached", "--name-status", "--", "docs/sequences/svg"],
    ).stdout.splitlines()
    assert svg_status in [
        ["D\tdocs/sequences/svg/01-a.svg", "A\tdocs/sequences/svg/02-b.svg"],
        ["R100\tdocs/sequences/svg/01-a.svg\tdocs/sequences/svg/02-b.svg"],
    ]


def test_pre_commit_hook_ignores_unstaged_sequence_delete_when_sync_runs(tmp_path):
    repo, env = _seed_two_sequence_repo(tmp_path)
    kept_svg = repo / "docs" / "sequences" / "svg" / "02-b.svg"
    updated_source = repo / "docs" / "sequences" / "01-a.puml"

    _write_sequence_source(updated_source, "updated")
    _run_repo_ok(repo, ["git", "add", "docs/sequences/01-a.puml"])
    (repo / "docs" / "sequences" / "02-b.puml").unlink()

    result = _run_repo(repo, ["sh", "hooks/pre-commit"], env=env)

    assert result.returncode == 0, result.stderr or result.stdout
    assert kept_svg.exists()
    assert _run_repo_ok(
        repo,
        ["git", "diff", "--cached", "--name-status", "--", "docs/sequences/svg"],
    ).stdout.splitlines() == ["M\tdocs/sequences/svg/01-a.svg"]


def test_pre_commit_hook_ignores_unstaged_sequence_delete_when_renderer_is_staged(tmp_path):
    repo, env = _seed_two_sequence_repo(tmp_path)
    kept_svg = repo / "docs" / "sequences" / "svg" / "02-b.svg"
    renderer_script = repo / "scripts" / "render_puml_svgs.py"

    renderer_script.write_text(
        renderer_script.read_text(encoding="utf-8") + "\n# staged hook test\n",
        encoding="utf-8",
    )
    _run_repo_ok(repo, ["git", "add", "scripts/render_puml_svgs.py"])
    (repo / "docs" / "sequences" / "02-b.puml").unlink()

    result = _run_repo(repo, ["sh", "hooks/pre-commit"], env=env)

    assert result.returncode == 0, result.stderr or result.stdout
    assert kept_svg.exists()
    assert _run_repo_ok(
        repo,
        ["git", "diff", "--cached", "--name-status", "--", "docs/sequences/svg"],
    ).stdout.splitlines() == []


def test_pre_push_hook_fails_for_stale_sequence_svg_before_other_checks(tmp_path):
    repo, env = _seed_sequence_repo(tmp_path)
    source = repo / "docs" / "sequences" / "01-a.puml"
    _write_sequence_source(source, "changed")
    _run_repo_ok(repo, ["git", "add", "docs/sequences/01-a.puml"])
    _run_repo_ok(repo, ["git", "commit", "-m", "stale source"])

    result = _run_repo(repo, ["sh", "hooks/pre-push"], env=env)

    assert result.returncode == 1
    assert "stale or missing: docs/sequences/svg/01-a.svg" in result.stdout
    assert "Running pre-push checks:" not in result.stdout
    assert "uv should not run" not in result.stderr


def test_pre_push_hook_fails_for_orphaned_sequence_svg_before_other_checks(tmp_path):
    repo, env = _seed_sequence_repo(tmp_path)
    _run_repo_ok(repo, ["git", "rm", "docs/sequences/01-a.puml"])
    _run_repo_ok(repo, ["git", "commit", "-m", "remove source only"])

    result = _run_repo(repo, ["sh", "hooks/pre-push"], env=env)

    assert result.returncode == 1
    assert "orphaned: docs/sequences/svg/01-a.svg" in result.stdout
    assert "Running pre-push checks:" not in result.stdout
    assert "uv should not run" not in result.stderr


def test_architecture_md_describes_ai_summary_as_primary_current_path():
    reality_today = _section_lines(ARCHITECTURE_MD.read_text(encoding="utf-8"), "## Reality Today")
    summary_line = next(line for line in reality_today if line.startswith("- Summary publication is currently file-driven"))

    assert "`ai-summary.md` as the primary current path" in summary_line
    assert "legacy/fallback summary content can still exist in the session folder" in summary_line


def test_architecture_md_has_sequence_toc_and_svg_refs():
    text = ARCHITECTURE_MD.read_text(encoding="utf-8")
    toc_lines = _section_lines(text, "## Table of Contents")
    toc_bullets = [line for line in toc_lines[1:] if line.startswith("- ") or line.startswith("  - ")]

    assert toc_bullets == [
        "- [Reality Today](#reality-today)",
        "- [C1 - System Context](#c1---system-context)",
        "- [C2 - Runtime Containers](#c2---runtime-containers)",
        "- [C3 - Railway Backend](#c3---railway-backend)",
        "- [C3 - Training Daemon and Local Host Runtime](#c3---training-daemon-and-local-host-runtime)",
        "- [Frontend Surfaces](#frontend-surfaces)",
        "- [State and Persistence](#state-and-persistence)",
        "- [Key Runtime Flows](#key-runtime-flows)",
        "- [Sequence Diagrams](#sequence-diagrams)",
        "  - [Session Lifecycle and Recovery](#session-lifecycle-and-recovery)",
        "  - [Participant Join and Geolocation](#participant-join-and-geolocation)",
        "  - [Poll and Quiz](#poll-and-quiz)",
        "  - [Q&A and Word Cloud](#qa-and-word-cloud)",
        "  - [Code Review and Debate](#code-review-and-debate)",
        "  - [Slides Cache and Follow Trainer](#slides-cache-and-follow-trainer)",
        "  - [Participant-to-Host Inputs and Emoji](#participant-to-host-inputs-and-emoji)",
        "  - [Activity, Summary, and Leaderboard](#activity-summary-and-leaderboard)",
        "- [Practical Implications](#practical-implications)",
    ]

    sequence_lines = _section_lines(text, "## Sequence Diagrams")
    subsections = _sequence_subsections(sequence_lines)

    assert [title for title, _ in subsections] == EXPECTED_SEQUENCE_TITLES

    for (title, lines), stem, summary in zip(
        subsections,
        EXPECTED_SEQUENCE_STEMS,
        EXPECTED_SEQUENCE_SUMMARIES,
        strict=True,
    ):
        body_lines = [line for line in lines if line and line != "---"]
        image_line = f"![{title.lower()}](docs/sequences/svg/{stem}.svg)"
        summary_line, code_path_line, image_line_in_doc = body_lines

        assert summary_line == summary
        assert "Current code path / behavior family:" in code_path_line
        assert image_line_in_doc == image_line
