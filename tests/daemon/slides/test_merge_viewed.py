"""Merging slide-viewing deltas, and the timeline they leave behind."""
from daemon.slides.merge_viewed import merge_slides_viewed

SLUGS = {"AI Coding.pptx": "agentic-engineering"}


def test_totals_accumulate_per_slide():
    viewed: list[dict] = []
    merge_slides_viewed(viewed, [{"fileName": "AI Coding.pptx", "page": 12, "seconds": 30}], SLUGS)
    merge_slides_viewed(viewed, [{"fileName": "AI Coding.pptx", "page": 12, "seconds": 45}], SLUGS)

    assert [(v["slug"], v["page"], v["seconds"]) for v in viewed] == [("agentic-engineering", 12, 75)]


def test_timeline_keeps_every_window_the_totals_collapse():
    """The whole point of the timeline: 12 → 13 → 12 is three moments, one total."""
    viewed: list[dict] = []
    timeline: list[dict] = []
    for page in (12, 13, 12):
        merge_slides_viewed(
            viewed,
            [{"fileName": "AI Coding.pptx", "page": page, "seconds": 20}],
            SLUGS,
            timeline=timeline,
        )

    assert [(v["page"], v["seconds"]) for v in viewed] == [(12, 40), (13, 20)]
    assert [m["page"] for m in timeline] == [12, 13, 12]
    assert all(m["seconds"] == 20 for m in timeline)
    # Stamped, and in the order they happened — that ordering is what a
    # transcript minute is looked up against.
    assert [m["at"] for m in timeline] == sorted(m["at"] for m in timeline)


def test_timeline_is_optional():
    viewed: list[dict] = []
    merge_slides_viewed(viewed, [{"fileName": "AI Coding.pptx", "page": 3, "seconds": 5}], SLUGS)
    assert viewed  # no timeline passed, nothing raised


def test_entries_without_a_known_deck_reach_neither_list():
    """An unmapped deck cannot be attributed, so it must not fake a moment."""
    viewed: list[dict] = []
    timeline: list[dict] = []
    merge_slides_viewed(
        viewed,
        [
            {"fileName": "Someone else.pptx", "page": 4, "seconds": 10},
            {"fileName": "AI Coding.pptx", "page": 4, "seconds": 0},
        ],
        SLUGS,
        timeline=timeline,
    )
    assert viewed == []
    assert timeline == []
