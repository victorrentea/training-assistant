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

    assert "## Table of Contents" in text
    for top_level_entry in [
        "- [Reality Today](#reality-today)",
        "- [C1 - System Context](#c1---system-context)",
        "- [C2 - Runtime Containers](#c2---runtime-containers)",
        "- [C3 - Railway Backend](#c3---railway-backend)",
        "- [C3 - Training Daemon and Local Host Runtime](#c3---training-daemon-and-local-host-runtime)",
        "- [Frontend Surfaces](#frontend-surfaces)",
        "- [State and Persistence](#state-and-persistence)",
        "- [Key Runtime Flows](#key-runtime-flows)",
        "- [Practical Implications](#practical-implications)",
        "- [Sequence Diagrams](#sequence-diagrams)",
    ]:
        assert top_level_entry in text

    assert "## Sequence Diagrams" in text

    for title, stem in zip(EXPECTED_SEQUENCE_TITLES, EXPECTED_SEQUENCE_STEMS, strict=True):
        anchor = title.lower().replace("&", "").replace(",", "").replace(" ", "-")
        alt_text = title.lower()

        assert f"- [{title}](#{anchor})" in text
        assert f"### {title}" in text
        assert f"![{alt_text}](docs/sequences/svg/{stem}.svg)" in text
