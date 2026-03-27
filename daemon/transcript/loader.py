"""
Transcript file loading and text extraction utilities.
"""

import re
import sys
from datetime import date
from pathlib import Path

from daemon import log
from daemon.config import MAX_CHARS_TO_CLAUDE

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_VTT_TS  = re.compile(r"(?:(\d+):)?(\d{2}):(\d{2})\.(\d{3})\s+-->")
_SRT_TS  = re.compile(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s+-->")
_SRT_SEQ = re.compile(r"^\d+$")
_TXT_TS_RE = re.compile(r"^\[\s*(?:\d{4}-\d{2}-\d{2}\s+)?(\d{2}):(\d{2}):(\d{2})\.\d+\s*\]\s*(.*)")
# Matches only lines that have the full ISO date prefix — used to detect real-clock files
_TXT_TS_ISO_RE = re.compile(r"^\[\s*\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+\s*\]")
_NORMALIZED_LINE_RE = re.compile(r"^\[\s*(\d{2}):(\d{2})\s*\]\s*(.*)$")
_NORMALIZED_TXT_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+transcription\.txt$", re.IGNORECASE)
_FILENAME_DATE_RE = re.compile(r"^(\d{8})\s+(\d{4})\b")

_CHARS_PER_MINUTE = 130 * 5


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

def _ts_to_seconds(h, m, s) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s)


def _is_elapsed_timestamps(timestamps: list[float]) -> bool:
    """Return True if timestamps look like elapsed-from-recording-start rather than wall-clock.

    WisperFlow historically used a cumulative elapsed counter that never resets,
    so timestamps can exceed 24 h.  Even when capped at <24 h, elapsed sessions
    start near 0 and the second meaningful cluster stays below 7 AM — a real
    recording starting at 9 AM or later would have its first real entry >= 07:00.
    Files that already contain ISO-date entries are handled separately (see _parse_txt).
    """
    if not timestamps:
        return False
    if max(timestamps) >= 86400:  # > 24 h -> impossible as clock time
        return True
    # Look at entries that have moved past the 2-minute init window
    second_cluster = [t for t in timestamps if t > 120]
    if not second_cluster:
        return True  # only init entries
    # If the earliest meaningful entry is before 7 AM it's almost certainly elapsed
    return min(second_cluster) < 7 * 3600


def _find_realclock_split(timestamps: list[float]) -> float | None:
    """Detect if a file switches from elapsed to real-clock mid-way.

    Some files have a small block of elapsed entries (WisperFlow init) followed by
    a big jump to real wall-clock entries (e.g. 00:00-00:08 elapsed, then 14:59 real).
    Returns the secs threshold at which real-clock entries start, or None if no split.
    """
    sorted_ts = sorted(set(t for t in timestamps if t > 0))
    if not sorted_ts:
        return None
    prev = 0.0
    for ts in sorted_ts:
        gap = ts - prev
        # A gap > 1 h that lands in realistic daytime (>= 07:00) signals a switch
        if gap > 3600 and ts >= 7 * 3600:
            return ts
        prev = ts
    return None


# ---------------------------------------------------------------------------
# Format-specific parsers
# ---------------------------------------------------------------------------

def _parse_vtt(text: str) -> list:
    entries, current_ts, current_lines = [], None, []
    for line in text.splitlines():
        line = line.strip()
        m = _VTT_TS.match(line)
        if m:
            if current_lines and current_ts is not None:
                entries.append((current_ts, " ".join(current_lines)))
            current_ts = _ts_to_seconds(m.group(1), m.group(2), m.group(3))
            current_lines = []
        elif line.startswith("WEBVTT") or line.startswith("NOTE") or not line:
            continue
        elif current_ts is not None:
            current_lines.append(line)
    if current_lines and current_ts is not None:
        entries.append((current_ts, " ".join(current_lines)))
    return entries


def _parse_srt(text: str) -> list:
    entries, current_ts, current_lines = [], None, []
    for line in text.splitlines():
        line = line.strip()
        m = _SRT_TS.match(line)
        if m:
            if current_lines and current_ts is not None:
                entries.append((current_ts, " ".join(current_lines)))
            current_ts = _ts_to_seconds(m.group(1), m.group(2), m.group(3))
            current_lines = []
        elif _SRT_SEQ.match(line) or not line:
            continue
        elif current_ts is not None:
            current_lines.append(line)
    if current_lines and current_ts is not None:
        entries.append((current_ts, " ".join(current_lines)))
    return entries


def _parse_txt(text: str, session_start_secs: int | None = None) -> list:
    """Parse a WisperFlow .txt transcript.

    session_start_secs: seconds-since-midnight of the recording start (from filename).
    When provided, elapsed-style timestamps are shifted to real wall-clock values.
    Files that already contain ISO-date-prefixed entries are left untouched because
    their HH values already represent real wall-clock time.
    """
    entries = []
    has_iso = False
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _TXT_TS_RE.match(line)
        if m:
            if _TXT_TS_ISO_RE.match(line):
                has_iso = True
            txt = m.group(4).strip() if m.group(4) else ""
            if txt:
                # Normalize "Speaker:\ttext" -> "Speaker: text"
                txt = txt.replace("\t", " ")
                entries.append((_ts_to_seconds(m.group(1), m.group(2), m.group(3)), txt))
        else:
            entries.append((None, line))

    # Convert elapsed -> real wall-clock only for plain-timestamp files
    if session_start_secs is not None and not has_iso:
        all_ts = [secs for secs, _ in entries if secs is not None]
        if _is_elapsed_timestamps(all_ts):
            # Check if file has a mixed format: elapsed init block + real-clock main block
            split = _find_realclock_split(all_ts)
            entries = [
                (secs + session_start_secs if secs is not None and (split is None or secs < split) else secs, txt)
                for secs, txt in entries
            ]

    return entries


def _parse_normalized_txt(text: str, day_offset_seconds: int = 0) -> list:
    """Parse normalized transcript lines: [HH:MM] Speaker: text.

    day_offset_seconds keeps chronological ordering when loading multiple days.
    """
    entries = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _NORMALIZED_LINE_RE.match(line)
        if not m:
            continue
        txt = m.group(3).strip()
        if not txt:
            continue
        hh, mm = int(m.group(1)), int(m.group(2))
        entries.append((day_offset_seconds + hh * 3600 + mm * 60, txt.replace("\t", " ")))
    return entries


# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------

def load_transcription_files(folder: Path, since_date: date | None = None) -> list:
    """Load transcription files from folder.

    If since_date is given, loads all files with a filename-embedded date >= since_date
    and concatenates their entries in chronological order (for multi-day sessions).
    If since_date is None, loads only the latest file (default behaviour).
    """

    def _sort_key(f: Path):
        """Prefer filename-embedded date; fall back to mtime."""
        nm = _NORMALIZED_TXT_NAME_RE.match(f.name)
        if nm:
            return nm.group(1).replace("-", "") + "9999"  # sort after raw files for same day
        m = _FILENAME_DATE_RE.match(f.name)
        if m:
            return m.group(1) + m.group(2)  # e.g. "202603222100"
        return str(f.stat().st_mtime)

    def _file_date(f: Path) -> date | None:
        nm = _NORMALIZED_TXT_NAME_RE.match(f.name)
        if nm:
            try:
                return date.fromisoformat(nm.group(1))
            except ValueError:
                return None
        m = _FILENAME_DATE_RE.match(f.name)
        if not m:
            return None
        ds = m.group(1)  # "YYYYMMDD"
        try:
            return date(int(ds[:4]), int(ds[4:6]), int(ds[6:8]))
        except ValueError:
            return None

    files = sorted([f for f in folder.iterdir() if f.suffix.lower() == ".txt"], key=_sort_key)
    if not files:
        log.error("transcript", f"No transcription files in {folder}")
        sys.exit(1)

    normalized_files = [f for f in files if _NORMALIZED_TXT_NAME_RE.match(f.name)]
    if not normalized_files:
        log.error("transcript", f"No normalized transcription files in {folder}")
        sys.exit(1)
    base_files = normalized_files

    if since_date is not None:
        qualifying = [f for f in base_files if (_file_date(f) or date.min) >= since_date]
        if not qualifying:
            qualifying = [base_files[-1]]  # fallback: at least load latest
    else:
        qualifying = [base_files[-1]]

    all_entries: list = []
    base_day = _file_date(qualifying[0]) if qualifying else None
    for f in qualifying:
        raw = f.read_text(encoding="utf-8", errors="replace")
        file_day = _file_date(f)
        day_offset = 0
        if base_day and file_day:
            day_offset = (file_day - base_day).days * 86400
        entries = _parse_normalized_txt(raw, day_offset_seconds=day_offset)
        all_entries.extend(entries)

    return all_entries


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_last_n_minutes(entries: list, minutes: int) -> str:
    timed = [(ts, txt) for ts, txt in entries if ts is not None]
    if timed:
        max_ts = max(ts for ts, _ in timed)
        cutoff = max_ts - minutes * 60
        selected = [(ts, txt) for ts, txt in entries if ts is not None and ts >= cutoff]
        log.info("transcript", f"Last {minutes} min (cutoff {max(0, cutoff/60):.1f} min mark)")
    else:
        budget = minutes * _CHARS_PER_MINUTE
        text = " ".join(txt for _, txt in entries)[-budget:]
        log.info("transcript", f"No timestamps — last ~{budget:,} chars")
        if len(text) > MAX_CHARS_TO_CLAUDE:
            text = text[-MAX_CHARS_TO_CLAUDE:]
            log.info("transcript", f"Text capped at {MAX_CHARS_TO_CLAUDE:,} chars")
        return text.strip()

    # Build clean text: add [HH:MM] markers only at ~1 min intervals
    parts: list[str] = []
    last_marker_ts: float = -120.0  # force first marker
    for ts, txt in selected:
        if ts - last_marker_ts >= 60:
            h, remainder = divmod(int(ts), 3600)
            m, _ = divmod(remainder, 60)
            parts.append(f"\n[{h % 24:02d}:{m:02d}]")
            last_marker_ts = ts
        parts.append(txt)
    text = " ".join(parts)

    if len(text) > MAX_CHARS_TO_CLAUDE:
        text = text[-MAX_CHARS_TO_CLAUDE:]
        log.info("transcript", f"Text capped at {MAX_CHARS_TO_CLAUDE:,} chars")
    return text.strip()


def extract_text_for_time_window(
    entries: list,
    start_ts: float,
    end_ts: float | None = None,
    exclude_ranges: list[tuple[float, float]] | None = None,
) -> str:
    """Extract transcript text within a time window, excluding nested session ranges.
    Timestamps are seconds-from-midnight. HH:MM markers added at ~1 min intervals."""
    exclude_ranges = exclude_ranges or []

    def _in_excluded(ts: float) -> bool:
        return any(lo <= ts < hi for lo, hi in exclude_ranges)

    selected = []
    for ts, txt in entries:
        if ts is None:
            continue
        if ts < start_ts:
            continue
        if end_ts is not None and ts >= end_ts:
            continue
        if _in_excluded(ts):
            continue
        selected.append((ts, txt))

    if not selected:
        return ""

    parts: list[str] = []
    last_marker_ts: float = -120.0
    for ts, txt in selected:
        if ts - last_marker_ts >= 60:
            h, remainder = divmod(int(ts), 3600)
            m, _ = divmod(remainder, 60)
            parts.append(f"\n[{h % 24:02d}:{m:02d}]")
            last_marker_ts = ts
        parts.append(txt)

    text = " ".join(parts)
    if len(text) > MAX_CHARS_TO_CLAUDE:
        text = text[-MAX_CHARS_TO_CLAUDE:]
    return text.strip()


def extract_all_text(entries: list) -> str:
    """Extract all transcript text with [HH:MM] markers at ~1 min intervals.

    Timestamps may exceed 86400 s (midnight crossings after elapsed->clock conversion);
    h % 24 keeps the displayed hour in the valid 0-23 range.
    """
    timed = [(ts, txt) for ts, txt in entries if ts is not None]
    if not timed:
        return " ".join(txt for _, txt in entries).strip()

    parts: list[str] = []
    last_marker_ts: float = -120.0
    for ts, txt in timed:
        if ts - last_marker_ts >= 60:
            h, remainder = divmod(int(ts), 3600)
            m, _ = divmod(remainder, 60)
            parts.append(f"\n[{h % 24:02d}:{m:02d}]")
            last_marker_ts = ts
        parts.append(txt)
    return " ".join(parts).strip()
