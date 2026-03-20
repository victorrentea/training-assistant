"""
Transcript delta tracking — sends only new text for incremental summaries.

The TranscriptStateManager tracks what transcript text has already been
processed and computes deltas so the summarizer only receives new content.
"""


class TranscriptStateManager:
    """Tracks transcript text already processed, computes deltas."""

    def __init__(self):
        self._last_full_text: str = ""

    def compute_delta(self, full_text: str) -> tuple[str, str]:
        """Given the full extracted transcript text, returns (delta_text, full_text).

        delta_text = only the NEW portion since last call.
        """
        if not self._last_full_text:
            self._last_full_text = full_text
            return full_text, full_text  # first call: everything is new

        # The transcript grows by appending new content at the end.
        # The sliding time window means old content drops off the start.
        # Strategy: find the longest suffix of old text that appears as prefix
        # in new text. Then delta = everything after that overlap.
        overlap_len = self._find_overlap_length(self._last_full_text, full_text)
        if overlap_len > 0:
            delta = full_text[overlap_len:]
        else:
            delta = full_text  # no overlap found, send everything

        self._last_full_text = full_text
        return delta.strip(), full_text

    def _find_overlap_length(self, old: str, new: str) -> int:
        """Find how many chars from start of `new` overlap with end of `old`.

        Uses anchor-based matching: tries a 500-char anchor from the end of
        old text, then falls back to 200-char, then to full old text for
        short strings.
        """
        if len(old) > 500:
            anchor = old[-500:]
            pos = new.find(anchor)
            if pos >= 0:
                return pos + len(anchor)

        if len(old) > 200:
            anchor = old[-200:]
            pos = new.find(anchor)
            if pos >= 0:
                return pos + len(anchor)

        # For shorter texts or as final fallback, try matching the full old text
        pos = new.find(old)
        if pos >= 0:
            return pos + len(old)

        return 0

    def reset(self):
        """Clear all tracked state."""
        self._last_full_text = ""
