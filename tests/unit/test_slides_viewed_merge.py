"""Unit tests for daemon.slides.merge_viewed."""

from daemon.slides.merge_viewed import merge_slides_viewed


def test_merge_into_empty():
    existing = []
    merge_slides_viewed(existing, [
        {"fileName": "AI.pptx", "page": 3, "seconds": 45},
        {"fileName": "AI.pptx", "page": 4, "seconds": 12},
    ])
    assert len(existing) == 2
    assert existing[0] == {"file_name": "AI.pptx", "page": 3, "seconds": 45}
    assert existing[1] == {"file_name": "AI.pptx", "page": 4, "seconds": 12}


def test_merge_adds_seconds_to_existing():
    existing = [{"file_name": "AI.pptx", "page": 3, "seconds": 100}]
    merge_slides_viewed(existing, [
        {"fileName": "AI.pptx", "page": 3, "seconds": 20},
    ])
    assert len(existing) == 1
    assert existing[0]["seconds"] == 120


def test_merge_preserves_order():
    existing = [
        {"file_name": "AI.pptx", "page": 1, "seconds": 10},
        {"file_name": "AI.pptx", "page": 2, "seconds": 20},
    ]
    merge_slides_viewed(existing, [
        {"fileName": "AI.pptx", "page": 2, "seconds": 5},
        {"fileName": "AI.pptx", "page": 3, "seconds": 30},
    ])
    assert len(existing) == 3
    assert existing[0] == {"file_name": "AI.pptx", "page": 1, "seconds": 10}
    assert existing[1] == {"file_name": "AI.pptx", "page": 2, "seconds": 25}
    assert existing[2] == {"file_name": "AI.pptx", "page": 3, "seconds": 30}


def test_merge_skips_zero_seconds():
    existing = []
    merge_slides_viewed(existing, [
        {"fileName": "AI.pptx", "page": 1, "seconds": 0},
    ])
    assert existing == []


def test_merge_skips_missing_fields():
    existing = []
    merge_slides_viewed(existing, [
        {"page": 1, "seconds": 10},
        {"fileName": "AI.pptx", "seconds": 10},
    ])
    assert existing == []


def test_merge_cross_deck():
    existing = [{"file_name": "AI.pptx", "page": 1, "seconds": 10}]
    merge_slides_viewed(existing, [
        {"fileName": "Java.pptx", "page": 1, "seconds": 30},
    ])
    assert len(existing) == 2
    assert existing[1] == {"file_name": "Java.pptx", "page": 1, "seconds": 30}
