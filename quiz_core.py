#!/usr/bin/env python3
"""
Shared core library for the training daemon and server.
"""

import base64
import json
import os
import re
import socket
from daemon import log
import ssl
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Optional

import anthropic
from daemon.llm_adapter import create_message

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SERVER_URL = "http://localhost:8000"
DEFAULT_MODEL      = "claude-sonnet-4-6"
DEFAULT_MINUTES    = 60
DEFAULT_TRANSCRIPT_MINUTES = 30  # default lookback window for transcript stats & summaries
MAX_CHARS_TO_CLAUDE = 60_000
DAEMON_POLL_INTERVAL = 3  # seconds


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class Config:
    folder: Path
    minutes: int
    server_url: str
    api_key: str
    model: str
    dry_run: bool
    host_username: str
    host_password: str
    topic: Optional[str] = None
    session_folder: Optional[Path] = None
    session_notes: Optional[Path] = None
    project_folder: Optional[str] = None


def load_secrets_env() -> None:
    """Load key=value pairs from secrets.env in the project directory into os.environ."""
    secrets_file = Path(__file__).parent / "secrets.env"
    if not secrets_file.exists():
        return
    for line in secrets_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def config_from_env(minutes: int = DEFAULT_MINUTES) -> Config:
    """Build a Config from environment variables (after loading secrets.env)."""
    load_secrets_env()
    folder = Path(os.environ.get("TRANSCRIPTION_FOLDER", "/Users/victorrentea/Documents/transcriptions"))
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        log.error("daemon", "ANTHROPIC_API_KEY is not set")
        sys.exit(1)
    if not folder.exists() or not folder.is_dir():
        log.error("transcript", f"Folder not found: {folder}")
        sys.exit(1)
    project_folder = os.environ.get("PROJECT_FOLDER")
    return Config(
        folder=folder,
        minutes=minutes,
        server_url=os.environ.get("WORKSHOP_SERVER_URL", DEFAULT_SERVER_URL).rstrip("/"),
        api_key=api_key,
        model=os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL),
        dry_run=False,
        host_username=os.environ.get("HOST_USERNAME", "host"),
        host_password=os.environ.get("HOST_PASSWORD", ""),
        project_folder=project_folder,
    )


_SESSION_FOLDER_RE = re.compile(
    r"^[^0-9]*(\d{4}-\d{2}-\d{2})(?:\.\.(\d{2}(?:-\d{2})?))?[\s_]"
)

MAX_SESSION_NOTES_CHARS = 20_000


def find_session_folder(today: date) -> tuple[Optional[Path], Optional[Path]]:
    """Returns (session_folder, session_notes). Both None if not found."""
    sessions_root_str = os.environ.get(
        "SESSIONS_FOLDER",
        str(Path.home() / "My Drive" / "Cursuri" / "###sesiuni"),
    )
    sessions_root = Path(sessions_root_str).expanduser()
    if not sessions_root.exists() or not sessions_root.is_dir():
        log.error("session", f"SESSIONS_FOLDER not found: {sessions_root}")
        return None, None

    matches: list[tuple[date, str, Path]] = []
    for entry in sessions_root.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.endswith(' talk'):
            continue
        m = _SESSION_FOLDER_RE.match(entry.name)
        if not m:
            continue
        try:
            start = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        g2 = m.group(2)
        try:
            if g2 is None:
                end = start
            elif "-" in g2:
                mm, dd = g2.split("-")
                end = date(start.year, int(mm), int(dd))
            else:
                end = date(start.year, start.month, int(g2))
        except ValueError:
            log.error("session", f"Invalid end date in: {entry.name}")
            continue
        if end < start:
            log.error("session", f"End < start in: {entry.name}")
            continue
        if start <= today <= end:
            matches.append((start, entry.name, entry))

    if not matches:
        return None, None

    if len(matches) > 1:
        log.error("session", f"Multiple folders match today: {[m[1] for m in matches]}")

    # Latest start_date; tie-break: alphabetically last name
    matches.sort(key=lambda x: (x[0], x[1]))
    _, _, session_folder = matches[-1]

    # Find most recently modified .txt file
    txt_files = sorted(
        [f for f in session_folder.iterdir() if f.suffix.lower() == ".txt"],
        key=lambda f: f.stat().st_mtime,
    )
    session_notes = txt_files[-1] if txt_files else None

    return session_folder, session_notes


def read_session_notes(config: Config) -> str:
    """Read session notes file from config.session_notes. Returns '' on missing/failure."""
    if not config.session_notes:
        return ""
    try:
        raw = config.session_notes.read_text(encoding="utf-8", errors="replace")
        if len(raw) > MAX_SESSION_NOTES_CHARS:
            log.error("session", f"Notes truncated to {MAX_SESSION_NOTES_CHARS:,} chars")
            raw = raw[-MAX_SESSION_NOTES_CHARS:]
        return raw.strip()
    except OSError as exc:
        log.error("session", f"Could not read notes: {exc}")
        return ""


# ---------------------------------------------------------------------------
# Transcription parsing
# ---------------------------------------------------------------------------

_VTT_TS  = re.compile(r"(?:(\d+):)?(\d{2}):(\d{2})\.(\d{3})\s+-->")
_SRT_TS  = re.compile(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s+-->")
_SRT_SEQ = re.compile(r"^\d+$")
_TXT_TS_RE = re.compile(r"^\[\s*(?:\d{4}-\d{2}-\d{2}\s+)?(\d{2}):(\d{2}):(\d{2})\.\d+\s*\]\s*(.*)")
# Matches only lines that have the full ISO date prefix — used to detect real-clock files
_TXT_TS_ISO_RE = re.compile(r"^\[\s*\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+\s*\]")


def _ts_to_seconds(h, m, s) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s)


def _is_elapsed_timestamps(timestamps: list[float]) -> bool:
    """Return True if timestamps look like elapsed-from-recording-start rather than wall-clock.

    WisperFlow historically used a cumulative elapsed counter that never resets,
    so timestamps can exceed 24 h.  Even when capped at <24 h, elapsed sessions
    start near 0 and the second meaningful cluster stays below 7 AM — a real
    recording starting at 9 AM or later would have its first real entry ≥ 07:00.
    Files that already contain ISO-date entries are handled separately (see _parse_txt).
    """
    if not timestamps:
        return False
    if max(timestamps) >= 86400:  # > 24 h → impossible as clock time
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
    a big jump to real wall-clock entries (e.g. 00:00–00:08 elapsed, then 14:59 real).
    Returns the secs threshold at which real-clock entries start, or None if no split.
    """
    sorted_ts = sorted(set(t for t in timestamps if t > 0))
    if not sorted_ts:
        return None
    prev = 0.0
    for ts in sorted_ts:
        gap = ts - prev
        # A gap > 1 h that lands in realistic daytime (≥ 07:00) signals a switch
        if gap > 3600 and ts >= 7 * 3600:
            return ts
        prev = ts
    return None


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
                # Normalize "Speaker:\ttext" → "Speaker: text"
                txt = txt.replace("\t", " ")
                entries.append((_ts_to_seconds(m.group(1), m.group(2), m.group(3)), txt))
        else:
            entries.append((None, line))

    # Convert elapsed → real wall-clock only for plain-timestamp files
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


_FILENAME_DATE_RE = re.compile(r"^(\d{8})\s+(\d{4})\b")
_NORMALIZED_TRANSCRIPT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\s+transcription\.txt$", re.IGNORECASE)


def load_transcription_files(folder: Path, since_date: date | None = None) -> list:
    """Load transcription files from folder.

    If since_date is given, loads all files with a filename-embedded date >= since_date
    and concatenates their entries in chronological order (for multi-day sessions).
    If since_date is None, loads only the latest file (default behaviour).
    """

    def _sort_key(f: Path):
        """Prefer filename-embedded date; fall back to mtime."""
        m = _FILENAME_DATE_RE.match(f.name)
        if m:
            return m.group(1) + m.group(2)  # e.g. "202603222100"
        return str(f.stat().st_mtime)

    def _file_date(f: Path) -> date | None:
        m = _FILENAME_DATE_RE.match(f.name)
        if not m:
            return None
        ds = m.group(1)  # "YYYYMMDD"
        try:
            return date(int(ds[:4]), int(ds[4:6]), int(ds[6:8]))
        except ValueError:
            return None

    files = sorted(
        [
            f
            for f in folder.iterdir()
            if f.suffix.lower() in {".txt", ".vtt", ".srt"}
            and not _NORMALIZED_TRANSCRIPT_RE.match(f.name)
        ],
        key=_sort_key,
    )
    if not files:
        log.error("transcript", f"No transcription files in {folder}")
        sys.exit(1)

    if since_date is not None:
        qualifying = [f for f in files if (_file_date(f) or date.min) >= since_date]
        if not qualifying:
            qualifying = [files[-1]]  # fallback: at least load latest
    else:
        qualifying = [files[-1]]

    all_entries: list = []
    for f in qualifying:
        raw = f.read_text(encoding="utf-8", errors="replace")
        ext = f.suffix.lower()
        if ext == ".vtt":
            entries = _parse_vtt(raw)
        elif ext == ".srt":
            entries = _parse_srt(raw)
        else:
            # Derive session start time from filename (e.g. "20250303 1402") so that
            # elapsed-style timestamps can be converted to real wall-clock values.
            session_start_secs = None
            fm = _FILENAME_DATE_RE.match(f.name)
            if fm:
                try:
                    h, mi = int(fm.group(2)[:2]), int(fm.group(2)[2:4])
                    session_start_secs = h * 3600 + mi * 60
                except (ValueError, IndexError):
                    pass
            entries = _parse_txt(raw, session_start_secs=session_start_secs)
        all_entries.extend(entries)

    return all_entries


# ---------------------------------------------------------------------------
# Time extraction
# ---------------------------------------------------------------------------

_CHARS_PER_MINUTE = 130 * 5


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

    Timestamps may exceed 86400 s (midnight crossings after elapsed→clock conversion);
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


# ---------------------------------------------------------------------------
# Claude API
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a quiz generator for technical training sessions.
You receive EITHER a transcript excerpt from a live workshop OR a specific topic/concept.
Your goal is to produce exactly ONE poll question designed to spark discussion among participants.
The question may have one OR multiple expected answers — choose whichever fits best.

Important transcript-quality warning:
- Live transcription may contain gibberish, repeated words, filler noise, speaker confusion, or nonsense fragments.
- Treat low-signal fragments as noise and prioritize coherent, repeated concepts that clearly appear in the transcript.
- Do not build the question around obvious transcription artifacts.

You have access to a tool `search_materials` that searches through technical materials.
Each result includes a `source_type` field: "slides" (workshop slides) or "book" (books/articles).
If you receive a topic or if the transcript mentions a complex pattern (like Outbox, Circuit Breaker, Resilience),
USE THE TOOL to find more details, nuances, and real-world examples to craft a better question.

When transcript text is provided, workflow priority is:
1) First identify the main topics from the transcript itself.
2) Build the question around those transcript topics.
3) Only then use reference materials (slides first, books second) to add depth, nuance, or examples.
4) Do not let reference materials override the main transcript focus.

IMPORTANT — source priority:
- PREFER slides over books: slides reflect exactly what the audience has seen and discussed.
  Use book content to add depth or nuance only when slides don't cover the concept.
- In the "source" field of your JSON response, mention the source type explicitly,
  e.g. "Circuit Breaker Slides, p. 12" or "Microservices Patterns (book), p. 85".

Also consult https://martinfowler.com/ for authoritative articles on patterns, architecture, and software design —
it is an excellent reference for grounding questions in well-known expert opinions and named concepts.

Respond with ONLY a valid JSON object in this exact schema:
{
  "question": "<the question text>",
  "options": ["<option A>", "<option B>", "<option C>", "<option D>"],
  "correct_indices": [<zero-based index>, ...],
  "source": "<Document Name, e.g. Microservices Patterns>",
  "page": "<Page number or reference, e.g. 85>"
}

Rules:
- If you used the tool, you MUST fill in the "source" and "page" fields based on the tool's output. Include source_type in the source name (e.g. "Circuit Breaker Slides, p. 12" or "Microservices Patterns (book), p. 85"). Prefer slide sources; use book sources only for depth.
- If a "QUESTIONS ALREADY ASKED THIS SESSION" section is provided, you MUST NOT generate a question that covers the same concept or tests the same knowledge — choose a clearly different topic or angle.
- The question must probe understanding of a CONCEPT, not trivial recall.
- Prefer questions where the answer is not obvious at first glance — the goal is to trigger debate.
- Draw on your broad knowledge AND the retrieved materials to craft richer, more nuanced options.
- Include at least one option that references a real-world pattern, anti-pattern, or expert opinion.
- Each option must be concise enough for a poll display (max 80 characters).
- Do not add any explanation, markdown code fences, or text outside the JSON object.

## Project Source Code
If `list_project_tree` and `read_project_file` tools are available, you have access to the training project's source code. When the transcript discusses specific classes, patterns, or configurations, use these tools to find the actual code and reference real class names, method signatures, and line numbers in your quiz questions. Start with `list_project_tree` to discover the project structure, then `read_project_file` for specific files mentioned in the transcript.
"""


_REFINE_OPTION_PROMPT = """\
The trainer wants to replace option {letter} ("{old_text}") with a different alternative.
Generate a new option that is distinct from all current options, plausible, and consistent
with the question and the training transcript.
Return the COMPLETE updated quiz JSON (same schema as before).
Return ONLY the JSON, no explanation.
"""

_REFINE_QUESTION_PROMPT = """\
The trainer wants an entirely new question with new options, based on the same transcript.
Generate a fresh question that covers a DIFFERENT concept than the current one.
Return the COMPLETE updated quiz JSON (same schema as before).
Return ONLY the JSON, no explanation.
"""


def _parse_raw_response(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try to find JSON block
        match = re.search(r"(\{.*\})", raw, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        raise

def search_materials(query: str) -> list:
    """Delegate to daemon/rag.py if available; graceful fallback otherwise."""
    try:
        from daemon.rag import search_materials as _search
        return _search(query)
    except ImportError:
        return [{"content": "RAG not available (run: pip install -e daemon/).", "source": "N/A", "page": "N/A"}]

def generate_quiz(text: str, config: Config) -> dict:
    prompt_content = text
    if config.topic:
        prompt_content = f"TOPIC: {config.topic}\n\n{text}" if text else f"TOPIC: {config.topic}"
    
    log.info("quiz", f"Requesting: {config.topic or f'last {config.minutes} min'}")
    
    tools = [
        {
            "name": "search_materials",
            "description": "Search through technical materials (slides and books) for concepts like Outbox, Circuit Breaker, Resilience, etc. Each result includes source_type ('slides' or 'book'). Prefer slides results as the audience has seen them.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query (e.g. 'Transactional Outbox pattern details')"}
                },
                "required": ["query"]
            }
        }
    ]
    from daemon.project_files import get_project_tools, handle_project_tool_call, PROJECT_TOOL_NAMES
    tools.extend(get_project_tools(config.project_folder))

    messages = [{"role": "user", "content": prompt_content}]
    
    try:
        while True:
            response = create_message(
                api_key=config.api_key,
                model=config.model, max_tokens=1000,
                system=_SYSTEM_PROMPT,
                messages=messages,
                tools=tools
            )
            
            # Append assistant's response to conversation
            messages.append({"role": "assistant", "content": response.content})
            
            if response.stop_reason == "tool_use":
                tool_use_blocks = [c for c in response.content if c.type == "tool_use"]
                
                tool_results = []
                for tool_call in tool_use_blocks:
                    if tool_call.name == "search_materials":
                        log.info("quiz", f"Claude searching: {tool_call.input['query']}")
                        search_results = search_materials(tool_call.input["query"])
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_call.id,
                            "content": json.dumps(search_results)
                        })
                    elif tool_call.name in PROJECT_TOOL_NAMES:
                        result = handle_project_tool_call(
                            tool_call.name, tool_call.input, config.project_folder
                        )
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_call.id,
                            "content": result
                        })
                    else:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_call.id,
                            "content": f"Error: unknown tool '{tool_call.name}'"
                        })
                
                # Append ALL tool results as a single user message
                messages.append({
                    "role": "user",
                    "content": tool_results
                })
                # Continue the loop
            else:
                raw = response.content[0].text
                break
                
    except anthropic.APIError as e:
        raise RuntimeError(f"Claude API error — {e}") from e
    
    try:
        quiz = _parse_raw_response(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Claude returned invalid JSON: {e}") from e
    _validate_quiz(quiz, raw)
    return quiz


def refine_quiz(quiz: dict, target: str, original_text: str, config: Config) -> dict:
    """Refine quiz using multi-turn conversation. target='question' or 'opt0'..'opt7'."""
    if target == "question":
        refine_prompt = _REFINE_QUESTION_PROMPT
    else:
        idx = int(target[3:])  # 'opt2' -> 2
        old_text = quiz["options"][idx] if idx < len(quiz["options"]) else "?"
        letter = chr(65 + idx)
        refine_prompt = _REFINE_OPTION_PROMPT.format(letter=letter, old_text=old_text)

    # Truncate transcript to save tokens — the quiz JSON already captures the key context
    REFINE_CONTEXT_CHARS = 5_000
    if len(original_text) > REFINE_CONTEXT_CHARS:
        truncated = original_text[-REFINE_CONTEXT_CHARS:]
        context_note = f"[Transcript context — last {len(truncated)} chars of {len(original_text)} total]\n{truncated}"
    else:
        context_note = original_text

    # Multi-turn: transcript → first generation → refine request
    messages = [
        {"role": "user", "content": context_note},
        {"role": "assistant", "content": json.dumps(quiz)},
        {"role": "user", "content": refine_prompt},
    ]
    try:
        response = create_message(
            api_key=config.api_key,
            model=config.model, max_tokens=600,
            system=_SYSTEM_PROMPT,
            messages=messages,
        )
    except anthropic.APIError as e:
        raise RuntimeError(f"Claude API error: {e}") from e
    raw = response.content[0].text
    try:
        updated = _parse_raw_response(raw)
    except json.JSONDecodeError:
        return quiz
    _validate_quiz(updated, raw)
    return updated



def _validate_quiz(quiz: dict, raw: str) -> None:
    if not isinstance(quiz.get("question"), str) or not quiz["question"].strip():
        _quiz_error("Missing or empty 'question'", raw)
    options = quiz.get("options")
    if not isinstance(options, list) or not (2 <= len(options) <= 8):
        _quiz_error("'options' must be a list of 2–8 strings", raw)
    if not all(isinstance(o, str) and o.strip() for o in options):
        _quiz_error("Each option must be a non-empty string", raw)
    ci = quiz.get("correct_indices")
    if not isinstance(ci, list) or len(ci) == 0 or not all(isinstance(i, int) and 0 <= i < len(options) for i in ci):
        _quiz_error(f"'correct_indices' must be a non-empty list of ints in range 0–{len(options)-1}", raw)


def print_quiz(quiz: dict) -> None:
    correct = set(quiz.get("correct_indices", []))
    log.info("quiz", "=" * 50)
    log.info("quiz", f"Q: {quiz['question']}")
    for i, opt in enumerate(quiz["options"]):
        marker = " <--" if i in correct else ""
        log.info("quiz", f"  {chr(65 + i)}. {opt}{marker}")
    if len(correct) > 1:
        log.info("quiz", f"  (multiple: {', '.join(chr(65+i) for i in sorted(correct))})")
    if quiz.get("source"):
        log.info("quiz", f"  source={quiz['source']} page={quiz.get('page', 'N/A')}")
    log.info("quiz", "=" * 50)


def _quiz_error(msg: str, raw: str) -> None:
    log.error("quiz", f"Invalid format: {msg}")
    raise RuntimeError(f"Invalid quiz format: {msg}")


# ---------------------------------------------------------------------------
# Server HTTP helpers
# ---------------------------------------------------------------------------

def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_HTTP_ERROR_HINTS = {
    401: "wrong credentials (check HOST_USERNAME / HOST_PASSWORD)",
    403: "access denied (check Caddy basic_auth config)",
    404: "endpoint not found (server may be outdated)",
    500: "server internal error (check uvicorn logs)",
    502: "bad gateway (reverse proxy issue — Caddy/nginx)",
    503: "server unavailable (workshop service may be down)",
}

_ANTHROPIC_ERROR_HINTS = {
    400: "bad request — check model name or prompt format",
    401: "invalid API key — check ANTHROPIC_API_KEY",
    403: "access denied — API key lacks permission",
    429: "rate limited or quota exceeded — wait and retry",
    500: "Anthropic server error — try again shortly",
    529: "Anthropic overloaded — try again in a few minutes",
}

_HTTP_TIMEOUT_SECONDS = float(os.environ.get("WORKSHOP_HTTP_TIMEOUT_SECONDS", "8"))


def _http_error_message(code: int, url: str) -> str:
    hint = _HTTP_ERROR_HINTS.get(code, "unexpected server response")
    return f"HTTP {code} — {hint} [{url}]"


def _request_json(url: str, payload: dict, method: str = "POST", username: str = "", password: str = "") -> dict:
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if username:
        headers["Authorization"] = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SECONDS, context=_ssl_context()) as resp:
            try:
                return json.loads(resp.read())
            except json.JSONDecodeError as e:
                raise RuntimeError(f"Invalid JSON response from server [{url}]") from e
    except urllib.error.HTTPError as e:
        raise RuntimeError(_http_error_message(e.code, url)) from e
    except (TimeoutError, socket.timeout) as e:
        raise RuntimeError(f"Server request timed out after {_HTTP_TIMEOUT_SECONDS:.1f}s [{url}]") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Cannot reach server: {e.reason} [{url}]") from e
    except OSError as e:
        raise RuntimeError(f"Cannot reach server: {e} [{url}]") from e


def _post_json(url: str, payload: dict, username: str = "", password: str = "") -> dict:
    return _request_json(url, payload, method="POST", username=username, password=password)


def _fetch_quiz_history(config: Config) -> str:
    """Fetch previously asked questions from the server as markdown. Returns '' on failure."""
    try:
        data = _get_json(f"{config.server_url}/api/quiz-md")
        return data.get("content", "").strip()
    except RuntimeError:
        return ""


def _put_json(url: str, payload: dict, username: str = "", password: str = "") -> dict:
    return _request_json(url, payload, method="PUT", username=username, password=password)


def _get_json(url: str, username: str = "", password: str = "") -> dict:
    headers = {}
    if username:
        headers["Authorization"] = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SECONDS, context=_ssl_context()) as resp:
            try:
                return json.loads(resp.read())
            except json.JSONDecodeError as e:
                raise RuntimeError(f"Invalid JSON response from server [{url}]") from e
    except urllib.error.HTTPError as e:
        raise RuntimeError(_http_error_message(e.code, url)) from e
    except (TimeoutError, socket.timeout) as e:
        raise RuntimeError(f"Server request timed out after {_HTTP_TIMEOUT_SECONDS:.1f}s [{url}]") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Cannot reach server: {e.reason} [{url}]") from e
    except OSError as e:
        raise RuntimeError(f"Cannot reach server: {e} [{url}]") from e


def post_poll(quiz: dict, config: Config) -> None:
    payload = {
        "question": quiz["question"],
        "options": quiz["options"],
        "multi": len(quiz.get("correct_indices", [])) > 1,
    }
    if quiz.get("source"):
        payload["question"] += f"\n\n(Source: {quiz['source']}, p. {quiz.get('page', 'N/A')})"
        
    _post_json(f"{config.server_url}/api/poll", payload, config.host_username, config.host_password)


def open_poll(config: Config) -> None:
    _put_json(f"{config.server_url}/api/poll/status", {"open": True}, config.host_username, config.host_password)


def post_status(status: str, message: str, config: Config,
                session_folder: Optional[str] = None,
                session_notes: Optional[str] = None,
                slides: Optional[list[dict]] = None) -> None:
    payload: dict = {"status": status, "message": message}
    if session_folder is not None or session_notes is not None:
        payload["session_folder"] = session_folder
        payload["session_notes"] = session_notes
    if slides is not None:
        payload["slides"] = slides
    try:
        _post_json(f"{config.server_url}/api/quiz-status",
                   payload,
                   config.host_username, config.host_password)
    except RuntimeError as e:
        log.error("daemon", f"Could not post status: {e}")



# ---------------------------------------------------------------------------
# Auto-generate (non-interactive, used by daemon)
# ---------------------------------------------------------------------------

def _fetch_summary_points(config: Config) -> list[dict]:
    """Fetch existing summary key points from the server. Returns [] on failure."""
    try:
        data = _get_json(f"{config.server_url}/api/summary")
        return data.get("points", [])
    except RuntimeError:
        return []


def auto_generate(minutes: int, config: Config) -> Optional[tuple]:
    """Load transcript → generate quiz → post preview. Returns (quiz, text) or None on failure."""
    post_status("generating", "Loading context…", config)

    notes = read_session_notes(config)

    # Prefer key points over raw transcript (saves tokens)
    summary_points = _fetch_summary_points(config)
    key_points_text = ""
    if summary_points:
        key_points_text = "\n".join(f"- [{p.get('time','')}] {p['text']}" for p in summary_points)

    text = ""
    if not key_points_text:
        # Fall back to raw transcript when no key points available
        entries = load_transcription_files(config.folder)
        if not entries:
            if not notes:
                post_status("error", "No transcription files or session notes found.", config)
                return None
        else:
            text = extract_last_n_minutes(entries, minutes)

    if not text and not key_points_text and not notes:
        post_status("error", "No content available for quiz generation.", config)
        return None

    # Assemble combined prompt
    parts = []
    if notes:
        parts.append(
            "SESSION NOTES (trainer's written agenda/key points — treat as primary source):\n" + notes
        )
    if key_points_text:
        parts.append(
            "KEY POINTS DISCUSSED (AI-extracted from live session — use as primary context):\n" + key_points_text
        )
    elif text:
        parts.append(
            f"TRANSCRIPT EXCERPT (last {minutes} min of live audio — use for context and recent topics):\n" + text
        )
    quiz_history = _fetch_quiz_history(config)
    if quiz_history:
        parts.append(
            "QUESTIONS ALREADY ASKED THIS SESSION (do NOT generate a similar question):\n" + quiz_history
        )
        if config.session_folder:
            try:
                (config.session_folder / "quiz.md").write_text(quiz_history, encoding="utf-8")
            except OSError as exc:
                log.error("quiz", f"Could not write quiz.md: {exc}")
    combined = "\n\n".join(parts)

    if key_points_text:
        status_detail = f"{len(summary_points)} key points"
    else:
        line_count = len([l for l in text.splitlines() if l.strip()])
        status_detail = f"{len(text):,} chars ({line_count} lines, last {minutes} min)"
    notes_info = f" + {len(notes):,} chars notes" if notes else ""
    post_status("generating", f"Sending {status_detail}{notes_info} to Claude…", config)

    try:
        quiz = generate_quiz(combined, config)
    except RuntimeError as e:
        post_status("error", str(e), config)
        return None

    print_quiz(quiz)

    try:
        _post_json(f"{config.server_url}/api/quiz-preview", {
            "question": quiz["question"],
            "options": quiz["options"],
            "multi": len(quiz.get("correct_indices", [])) > 1,
            "correct_indices": quiz.get("correct_indices", []),
            "source": quiz.get("source"),
            "page": quiz.get("page"),
        }, config.host_username, config.host_password)
    except RuntimeError as e:
        post_status("error", f"Failed to post preview: {e}", config)
        return None

    post_status("done", "✅ Question ready — review and fire from host panel.", config)
    return quiz, combined


def auto_generate_topic(topic: str, config: Config) -> Optional[tuple]:
    """Generate a quiz from a topic using RAG. Returns (quiz, topic_context) or None."""
    post_status("generating", f"Generating question about '{topic}'…", config)
    notes = read_session_notes(config)
    notes_text = (
        "SESSION NOTES (trainer's written agenda/key points — treat as primary source):\n" + notes
        if notes else ""
    )
    quiz_history = _fetch_quiz_history(config)
    quiz_history_text = (
        "\n\nQUESTIONS ALREADY ASKED THIS SESSION (do NOT generate a similar question):\n" + quiz_history
        if quiz_history else ""
    )
    topic_config = replace(config, topic=topic)
    try:
        quiz = generate_quiz(notes_text + quiz_history_text, topic_config)
    except RuntimeError as e:
        post_status("error", str(e), topic_config)
        return None
    print_quiz(quiz)
    topic_context = f"TOPIC: {topic}"
    try:
        _post_json(f"{config.server_url}/api/quiz-preview", {
            "question": quiz["question"],
            "options": quiz["options"],
            "multi": len(quiz.get("correct_indices", [])) > 1,
            "correct_indices": quiz.get("correct_indices", []),
            "source": quiz.get("source"),
            "page": quiz.get("page"),
        }, config.host_username, config.host_password)
    except RuntimeError as e:
        post_status("error", f"Failed to post preview: {e}", config)
        return None
    post_status("done", "✅ Question ready — review and fire from host panel.", config)
    return quiz, topic_context


def auto_refine(target: str, current_quiz: dict, original_text: str, config: Config) -> Optional[dict]:
    """Refine a specific option or the whole question. Returns updated quiz or None on failure."""
    label = "question" if target == "question" else f"option {chr(65 + int(target[3:]))}"
    post_status("generating", f"Regenerating {label}…", config)
    try:
        updated = refine_quiz(current_quiz, target, original_text, config)
    except RuntimeError as e:
        post_status("error", f"Claude API error: {e}", config)
        return None

    print_quiz(updated)
    try:
        _post_json(f"{config.server_url}/api/quiz-preview", {
            "question": updated["question"],
            "options": updated["options"],
            "multi": len(updated.get("correct_indices", [])) > 1,
            "correct_indices": updated.get("correct_indices", []),
            "source": updated.get("source"),
            "page": updated.get("page"),
        }, config.host_username, config.host_password)
    except RuntimeError as e:
        post_status("error", f"Failed to post updated preview: {e}", config)
        return None

    post_status("done", "✅ Updated — review and fire from host panel.", config)
    return updated
