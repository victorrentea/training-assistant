from pathlib import Path

import scripts.render_puml_svgs as renderer


ROOT = Path(__file__).resolve().parents[2]
SEQUENCES_DIR = ROOT / "docs" / "sequences"
SVG_DIR = SEQUENCES_DIR / "svg"
ARCHITECTURE_MD = ROOT / "ARCHITECTURE.md"
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

    for (title, lines), stem in zip(subsections, EXPECTED_SEQUENCE_STEMS, strict=True):
        body_lines = [line for line in lines if line and line != "---"]
        image_line = f"![{title.lower()}](docs/sequences/svg/{stem}.svg)"

        assert body_lines[0]
        assert body_lines[1].startswith("Current code path / behavior family: ")
        assert body_lines[-1] == image_line
