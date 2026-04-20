"""Unit tests for daemon.slides.merge_viewed."""

from daemon.slides.merge_viewed import merge_slides_viewed

SLUG_MAP = {"AI.pptx": "ai", "Java.pptx": "java"}


def test_merge_into_empty():
    existing = []
    merge_slides_viewed(existing, [
        {"fileName": "AI.pptx", "page": 3, "seconds": 45},
        {"fileName": "AI.pptx", "page": 4, "seconds": 12},
    ], slug_for_filename=SLUG_MAP)
    assert len(existing) == 2
    assert existing[0]["slug"] == "ai"
    assert existing[0]["page"] == 3
    assert existing[0]["seconds"] == 45
    assert existing[0]["last_seen_at"] is not None
    assert existing[1]["slug"] == "ai"
    assert existing[1]["page"] == 4
    assert existing[1]["seconds"] == 12


def test_merge_adds_seconds_to_existing():
    existing = [{"slug": "ai", "page": 3, "seconds": 100, "last_seen_at": "2024-01-01T00:00:00+00:00"}]
    merge_slides_viewed(existing, [
        {"fileName": "AI.pptx", "page": 3, "seconds": 20},
    ], slug_for_filename=SLUG_MAP)
    assert len(existing) == 1
    assert existing[0]["seconds"] == 120
    assert existing[0]["last_seen_at"] != "2024-01-01T00:00:00+00:00"


def test_merge_preserves_order():
    existing = [
        {"slug": "ai", "page": 1, "seconds": 10, "last_seen_at": None},
        {"slug": "ai", "page": 2, "seconds": 20, "last_seen_at": None},
    ]
    merge_slides_viewed(existing, [
        {"fileName": "AI.pptx", "page": 2, "seconds": 5},
        {"fileName": "AI.pptx", "page": 3, "seconds": 30},
    ], slug_for_filename=SLUG_MAP)
    assert len(existing) == 3
    assert existing[0]["slug"] == "ai" and existing[0]["page"] == 1 and existing[0]["seconds"] == 10
    assert existing[1]["slug"] == "ai" and existing[1]["page"] == 2 and existing[1]["seconds"] == 25
    assert existing[2]["slug"] == "ai" and existing[2]["page"] == 3 and existing[2]["seconds"] == 30


def test_merge_skips_zero_seconds():
    existing = []
    merge_slides_viewed(existing, [
        {"fileName": "AI.pptx", "page": 1, "seconds": 0},
    ], slug_for_filename=SLUG_MAP)
    assert existing == []


def test_merge_skips_missing_fields():
    existing = []
    merge_slides_viewed(existing, [
        {"page": 1, "seconds": 10},
        {"fileName": "AI.pptx", "seconds": 10},
    ], slug_for_filename=SLUG_MAP)
    assert existing == []


def test_merge_cross_deck():
    existing = [{"slug": "ai", "page": 1, "seconds": 10, "last_seen_at": None}]
    merge_slides_viewed(existing, [
        {"fileName": "Java.pptx", "page": 1, "seconds": 30},
    ], slug_for_filename=SLUG_MAP)
    assert len(existing) == 2
    assert existing[1]["slug"] == "java" and existing[1]["page"] == 1 and existing[1]["seconds"] == 30
    assert existing[1]["last_seen_at"] is not None
