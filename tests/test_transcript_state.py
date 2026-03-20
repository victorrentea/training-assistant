"""Tests for TranscriptStateManager — delta tracking for incremental summaries."""

import pytest
from daemon.transcript_state import TranscriptStateManager


class TestTranscriptStateManager:
    def setup_method(self):
        self.mgr = TranscriptStateManager()

    def test_first_call_returns_full_text_as_delta(self):
        full = "Hello world. This is a transcript."
        delta, returned_full = self.mgr.compute_delta(full)
        assert delta == full
        assert returned_full == full

    def test_second_call_with_appended_text_returns_only_new_portion(self):
        original = "Line one. Line two. Line three."
        self.mgr.compute_delta(original)

        appended = original + " Line four. Line five."
        delta, returned_full = self.mgr.compute_delta(appended)
        assert delta == "Line four. Line five."
        assert returned_full == appended

    def test_sliding_window_finds_overlap_and_returns_delta(self):
        """Sliding window: old content drops off the start, new content appended at end."""
        text_v1 = "A B C D E F G H I J K L M N O P Q R S T U V W X Y Z " * 10
        # v2: drop the first chunk, add new content at the end
        text_v2 = text_v1[50:] + " NEW CONTENT APPENDED HERE"
        self.mgr.compute_delta(text_v1)

        delta, returned_full = self.mgr.compute_delta(text_v2)
        assert "NEW CONTENT APPENDED HERE" in delta
        assert returned_full == text_v2
        # Delta should NOT contain the overlapping portion
        # The overlap is the suffix of v1 that appears as prefix of v2
        assert len(delta) < len(text_v2)

    def test_completely_different_text_returns_full_text(self):
        self.mgr.compute_delta("First transcript content that is unique.")

        completely_new = "Totally different content with no overlap whatsoever."
        delta, returned_full = self.mgr.compute_delta(completely_new)
        assert delta == completely_new
        assert returned_full == completely_new

    def test_reset_clears_state(self):
        original = "Some transcript text here."
        self.mgr.compute_delta(original)
        self.mgr.reset()

        # After reset, same text should be returned as full delta again
        delta, returned_full = self.mgr.compute_delta(original)
        assert delta == original
        assert returned_full == original

    def test_empty_delta_when_text_unchanged(self):
        text = "Same text repeated."
        self.mgr.compute_delta(text)
        delta, returned_full = self.mgr.compute_delta(text)
        assert delta == ""
        assert returned_full == text

    def test_short_text_overlap_still_works(self):
        """Even short text gets overlap detection via full-text fallback."""
        short = "Hi"
        self.mgr.compute_delta(short)
        new_text = "Hi there"
        delta, _ = self.mgr.compute_delta(new_text)
        assert delta == "there"
