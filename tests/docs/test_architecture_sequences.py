from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SEQUENCES_DIR = ROOT / "docs" / "sequences"
SVG_DIR = SEQUENCES_DIR / "svg"
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


def test_expected_sequence_source_files_exist():
    missing = [
        SEQUENCES_DIR / f"{stem}.puml"
        for stem in EXPECTED_SEQUENCE_STEMS
        if not (SEQUENCES_DIR / f"{stem}.puml").is_file()
    ]

    assert missing == []


def test_expected_sequence_svg_files_exist():
    missing = [
        SVG_DIR / f"{stem}.svg"
        for stem in EXPECTED_SEQUENCE_STEMS
        if not (SVG_DIR / f"{stem}.svg").is_file()
    ]

    assert missing == []
