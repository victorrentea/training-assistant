#!/usr/bin/env python3
"""
Quiz Generator — companion CLI for the Workshop Live Interaction Tool.

Reads the last N minutes of transcription from a local folder, sends the text
to the Claude API, and posts the generated quiz as a live poll to the workshop server.

Usage:
    python quiz_generator.py --folder /path/to/transcripts --minutes 30

Environment variables (override with CLI flags):
    ANTHROPIC_API_KEY       Claude API key (required)
    WORKSHOP_SERVER_URL     Workshop server base URL (default: http://localhost:8000)
    TRANSCRIPTION_FOLDER    Path to transcription files folder
"""

import argparse
import base64
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import anthropic

# ---------------------------------------------------------------------------
# Configuration & CLI
# ---------------------------------------------------------------------------

DEFAULT_SERVER_URL = "http://localhost:8000"
DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MINUTES = 60
MAX_CHARS_TO_CLAUDE = 60_000  # Hard cap to control API cost


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


def _load_secrets_env() -> None:
    """Load key=value pairs from secrets.env in the script's directory into os.environ."""
    secrets_file = Path(__file__).parent / "secrets.env"
    if not secrets_file.exists():
        return
    for line in secrets_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def parse_args() -> Config:
    _load_secrets_env()
    parser = argparse.ArgumentParser(
        description="Generate a quiz from live transcription and post it as a workshop poll."
    )
    parser.add_argument(
        "--folder",
        default=os.environ.get("TRANSCRIPTION_FOLDER", "/Users/victorrentea/Documents/transcriptions"),
        help="Path to folder containing transcription files (.txt, .vtt, .srt)",
    )
    parser.add_argument(
        "--minutes",
        type=int,
        default=int(os.environ.get("QUIZ_MINUTES", DEFAULT_MINUTES)),
        help=f"How many minutes of recent transcription to use (default: {DEFAULT_MINUTES})",
    )
    parser.add_argument(
        "--server",
        default=os.environ.get("WORKSHOP_SERVER_URL", DEFAULT_SERVER_URL),
        help=f"Workshop server base URL (default: {DEFAULT_SERVER_URL})",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("ANTHROPIC_API_KEY"),
        help="Anthropic API key (or set ANTHROPIC_API_KEY env var)",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL),
        help=f"Claude model to use (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the generated quiz without posting to the server",
    )
    parser.add_argument(
        "--host-username",
        default=os.environ.get("HOST_USERNAME", "host"),
        help="Basic Auth username for the workshop server (default: host)",
    )
    parser.add_argument(
        "--host-password",
        default=os.environ.get("HOST_PASSWORD", ""),
        help="Basic Auth password for the workshop server (or set HOST_PASSWORD env var)",
    )

    args = parser.parse_args()

    if not args.folder:
        parser.error(
            "Transcription folder is required. Use --folder or set TRANSCRIPTION_FOLDER."
        )
    if not args.api_key:
        parser.error(
            "Anthropic API key is required. Use --api-key or set ANTHROPIC_API_KEY."
        )

    folder = Path(args.folder)
    if not folder.exists() or not folder.is_dir():
        parser.error(f"Folder not found: {folder}")

    return Config(
        folder=folder,
        minutes=args.minutes,
        server_url=args.server.rstrip("/"),
        api_key=args.api_key,
        model=args.model,
        dry_run=args.dry_run,
        host_username=args.host_username,
        host_password=args.host_password,
    )


# ---------------------------------------------------------------------------
# Transcription parsing
# ---------------------------------------------------------------------------

# Matches WebVTT timestamps: optional HH: then MM:SS.mmm -->
_VTT_TS = re.compile(r"(?:(\d+):)?(\d{2}):(\d{2})\.(\d{3})\s+-->")
# Matches SRT timestamps: HH:MM:SS,mmm -->
_SRT_TS = re.compile(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s+-->")
# Bare integer line (SRT sequence number)
_SRT_SEQ = re.compile(r"^\d+$")
# Matches this app's .txt format: [HH:MM:SS.xx] Speaker:\ttext
_TXT_TS = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\.\d+\]\s+[^:]+:\t(.*)")


def _ts_to_seconds(h, m, s) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s)


def _parse_vtt(text: str) -> list[tuple[Optional[float], str]]:
    """Parse WebVTT content into (timestamp_seconds, text) pairs."""
    entries: list = []
    current_ts: Optional[float] = None
    current_lines: list[str] = []

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


def _parse_srt(text: str) -> list[tuple[Optional[float], str]]:
    """Parse SRT content into (timestamp_seconds, text) pairs."""
    entries: list = []
    current_ts: Optional[float] = None
    current_lines: list[str] = []

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


def _parse_txt(text: str) -> list[tuple[Optional[float], str]]:
    """Parse plain text. Handles '[HH:MM:SS.xx] Speaker:\\ttext' format if present."""
    entries = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _TXT_TS.match(line)
        if m:
            ts = _ts_to_seconds(m.group(1), m.group(2), m.group(3))
            entries.append((ts, m.group(4).strip()))
        else:
            entries.append((None, line))
    return entries


def load_transcription_files(folder: Path) -> list[tuple[Optional[float], str]]:
    """
    Load the most recently modified transcription file from folder.
    Returns a list of (timestamp_seconds_or_None, text) tuples.
    """
    files = sorted(
        [f for f in folder.iterdir() if f.suffix.lower() in {".txt", ".vtt", ".srt"}],
        key=lambda f: f.stat().st_mtime,
    )

    if not files:
        print(f"[error] No .txt, .vtt, or .srt files found in {folder}", file=sys.stderr)
        sys.exit(1)

    latest = files[-1]
    print(f"[info] Using latest transcription: {latest.name}")

    all_entries: list = []
    time_offset = 0.0

    for i, f in enumerate([latest]):
        raw = f.read_text(encoding="utf-8", errors="replace")
        ext = f.suffix.lower()

        if ext == ".vtt":
            entries = _parse_vtt(raw)
        elif ext == ".srt":
            entries = _parse_srt(raw)
        else:
            entries = _parse_txt(raw)

        # Offset timed entries so files form a continuous global timeline.
        # For files after the first, derive offset from mtime gaps.
        if i > 0 and entries:
            prev_mtime = files[i - 1].stat().st_mtime
            curr_mtime = f.stat().st_mtime
            # Assume previous file ends at its last timestamp + small buffer
            prev_entries = all_entries
            last_timed = next(
                (ts for ts, _ in reversed(prev_entries) if ts is not None), None
            )
            if last_timed is not None:
                time_offset = last_timed + (curr_mtime - prev_mtime)
            else:
                time_offset = curr_mtime - files[0].stat().st_mtime

        if entries:
            offsetted = [
                (ts + time_offset if ts is not None else None, txt)
                for ts, txt in entries
            ]
            all_entries.extend(offsetted)
            print(f"[info]   {f.name}: {len(entries)} segments")

    return all_entries


# ---------------------------------------------------------------------------
# Time extraction
# ---------------------------------------------------------------------------

# Rough heuristic for plain text without timestamps: 130 wpm × 5 chars/word
_CHARS_PER_MINUTE = 130 * 5


def extract_last_n_minutes(
    entries: list, minutes: int
) -> str:
    """Extract text from the last `minutes` minutes of transcription."""
    timed = [(ts, txt) for ts, txt in entries if ts is not None]

    if timed:
        max_ts = max(ts for ts, _ in timed)
        cutoff = max_ts - minutes * 60
        recent = [txt for ts, txt in entries if ts is None or ts >= cutoff]
        text = " ".join(recent)
        print(
            f"[info] Using timestamp-based extraction "
            f"(last {minutes} min, cutoff at {max(0, cutoff/60):.1f} min mark)"
        )
    else:
        # Fallback: character budget estimate
        budget = minutes * _CHARS_PER_MINUTE
        full_text = " ".join(txt for _, txt in entries)
        text = full_text[-budget:]
        print(
            f"[info] No timestamps found — using last ~{budget:,} chars "
            f"(≈{minutes} min at 130 wpm)"
        )

    # Hard cap to control API cost
    if len(text) > MAX_CHARS_TO_CLAUDE:
        text = text[-MAX_CHARS_TO_CLAUDE:]
        print(f"[info] Text capped at {MAX_CHARS_TO_CLAUDE:,} chars to control API cost")

    return text.strip()


# ---------------------------------------------------------------------------
# Claude API — quiz generation
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a quiz generator for technical training sessions.
You receive a transcript excerpt from a live workshop and you produce
exactly ONE poll question designed to spark discussion among participants.
The question may have one OR multiple expected answers — choose whichever fits best.

Respond with ONLY a valid JSON object in this exact schema:
{
  "question": "<the question text>",
  "options": ["<option A>", "<option B>", "<option C>", "<option D>"],
  "correct_indices": [<zero-based index>, ...]
}

Rules:
- The question must probe understanding of a CONCEPT from the transcript,
  not trivial recall of a specific phrase.
- Prefer questions where the answer is not obvious at first glance — the goal is
  to reveal disagreement and trigger debate, not to test rote memory.
- Draw on your broad knowledge of the field (books, research papers, industry
  best practices, well-known experts) to craft richer, more nuanced options —
  not just options derived directly from the transcript text.
- Include at least one option that references a real-world pattern, anti-pattern,
  or expert opinion that extends beyond what was explicitly said in the transcript.
- If multiple answers are expected, start the question with "Which of the following..."
  and list all expected indices in correct_indices.
- All options must be plausible; distractors should reflect common misconceptions
  or subtly wrong interpretations from real-world practice.
- Each option must be concise enough for a poll display (max 80 characters).
- Do not add any explanation, markdown code fences, or text outside the JSON object.
"""

_REFINE_SYSTEM = """\
You previously generated a quiz question. The trainer has requested a change to one option.
Apply the requested change and return the COMPLETE updated quiz JSON in the same schema:
{
  "question": "<the question text>",
  "options": ["<option A>", "<option B>", "<option C>", "<option D>"],
  "correct_indices": [<zero-based index>, ...]
}
Return ONLY the JSON, no explanation.
"""


def _parse_raw_response(raw: str) -> dict:
    """Parse and strip markdown fences from a Claude response."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        raw = raw.strip()
    return json.loads(raw)


def generate_quiz(text: str, config: Config) -> dict:
    """Send transcript text to Claude and return a parsed quiz dict."""
    client = anthropic.Anthropic(api_key=config.api_key)

    print(f"[info] Sending {len(text):,} chars to {config.model}...")

    try:
        response = client.messages.create(
            model=config.model,
            max_tokens=600,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text}],
        )
    except anthropic.APIError as e:
        print(f"[error] Claude API error: {e}", file=sys.stderr)
        sys.exit(1)

    raw = response.content[0].text
    try:
        quiz = _parse_raw_response(raw)
    except json.JSONDecodeError as e:
        print(f"[error] Claude returned invalid JSON: {e}", file=sys.stderr)
        print(f"[error] Raw response:\n{raw}", file=sys.stderr)
        sys.exit(1)

    _validate_quiz(quiz, raw)
    return quiz


def refine_option(quiz: dict, feedback: str, config: Config) -> dict:
    """Ask Claude to update one option based on free-text trainer feedback."""
    client = anthropic.Anthropic(api_key=config.api_key)

    current = json.dumps(quiz, indent=2)
    try:
        response = client.messages.create(
            model=config.model,
            max_tokens=600,
            system=_REFINE_SYSTEM,
            messages=[
                {"role": "user", "content": f"Current quiz:\n{current}\n\nRequested change: {feedback}"},
            ],
        )
    except anthropic.APIError as e:
        print(f"[error] Claude API error: {e}", file=sys.stderr)
        sys.exit(1)

    raw = response.content[0].text
    try:
        updated = _parse_raw_response(raw)
    except json.JSONDecodeError as e:
        print(f"[error] Claude returned invalid JSON: {e}", file=sys.stderr)
        print(f"[error] Raw response:\n{raw}", file=sys.stderr)
        return quiz  # keep original on parse failure

    _validate_quiz(updated, raw)
    return updated


def _validate_quiz(quiz: dict, raw: str) -> None:
    """Validate the quiz dict has the expected shape. Exits on failure."""
    if not isinstance(quiz.get("question"), str) or not quiz["question"].strip():
        _quiz_error("Missing or empty 'question'", raw)
    options = quiz.get("options")
    if not isinstance(options, list) or not (2 <= len(options) <= 8):
        _quiz_error("'options' must be a list of 2–8 strings", raw)
    if not all(isinstance(o, str) and o.strip() for o in options):
        _quiz_error("Each option must be a non-empty string", raw)
    ci = quiz.get("correct_indices")
    if (
        not isinstance(ci, list)
        or len(ci) == 0
        or not all(isinstance(i, int) and 0 <= i < len(options) for i in ci)
    ):
        _quiz_error(f"'correct_indices' must be a non-empty list of ints in range 0–{len(options)-1}", raw)


def _print_quiz(quiz: dict) -> None:
    correct = set(quiz.get("correct_indices", []))
    print()
    print("=" * 60)
    print(f"Q: {quiz['question']}")
    print()
    for i, opt in enumerate(quiz["options"]):
        marker = " ✅" if i in correct else ""
        print(f"  {chr(65 + i)}. {opt}{marker}")
    if len(correct) > 1:
        print(f"\n  (multiple expected: {', '.join(chr(65+i) for i in sorted(correct))})")
    print("=" * 60)
    print()


def _quiz_error(msg: str, raw: str) -> None:
    print(f"[error] Invalid quiz format: {msg}", file=sys.stderr)
    print(f"[error] Raw response:\n{raw}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Workshop server integration
# ---------------------------------------------------------------------------

def _ssl_context() -> ssl.SSLContext:
    """Return an SSL context with certifi's CA bundle (fixes macOS Python cert issues)."""
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    return ctx


def _post_json(url: str, payload: dict, username: str = "", password: str = "") -> dict:
    """POST JSON to a URL and return the parsed response. Raises on HTTP error."""
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if username:
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, context=_ssl_context()) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} from {url}: {body}") from e


def post_poll(quiz: dict, config: Config) -> None:
    """Create the poll on the workshop server."""
    payload = {
        "question": quiz["question"],
        "options": quiz["options"],
        "multi": len(quiz.get("correct_indices", [])) > 1,
    }
    _post_json(f"{config.server_url}/api/poll", payload, config.host_username, config.host_password)


def open_poll(config: Config) -> None:
    """Open the poll for voting."""
    _post_json(f"{config.server_url}/api/poll/status", {"open": True}, config.host_username, config.host_password)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    config = parse_args()

    # 1. Load transcription files
    entries = load_transcription_files(config.folder)
    if not entries:
        print("[error] No transcription content found.", file=sys.stderr)
        sys.exit(1)

    # 2. Extract last N minutes
    text = extract_last_n_minutes(entries, config.minutes)
    if not text:
        print(
            f"[error] Extracted text is empty. "
            f"Try increasing --minutes or check the transcription files.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[info] Extracted {len(text):,} characters covering the last {config.minutes} minutes")

    # 3. Generate quiz via Claude
    quiz = generate_quiz(text, config)

    # 4. Feedback loop — preview, optionally refine, then confirm
    while True:
        _print_quiz(quiz)

        if config.dry_run:
            print("[dry-run] Skipping post to server.")
            return

        n_opts = len(quiz["options"])
        opt_letters = "/".join(chr(65 + i) for i in range(n_opts))
        print(f"  [y] Post to server   [{opt_letters}] Replace that option   [n] Abort")
        try:
            answer = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return

        if answer == "y":
            break
        elif answer == "n":
            print("Aborted.")
            return
        elif len(answer) == 1 and answer.isalpha() and (idx := ord(answer.upper()) - 65) < n_opts:
            opt_label = chr(65 + idx)
            try:
                feedback = input(f"Replace option {opt_label} with what? ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nAborted.")
                return
            if feedback:
                print("[info] Asking Claude to refine...")
                quiz = refine_option(quiz, f"replace option {opt_label} with: {feedback}", config)
        elif answer == "r":
            try:
                feedback = input("Describe the change (e.g. 'replace option B with a better distractor about X'): ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nAborted.")
                return
            if feedback:
                print("[info] Asking Claude to refine...")
                quiz = refine_option(quiz, feedback, config)
        # any other input — just re-show the menu

    # 6. Post and open
    try:
        post_poll(quiz, config)
        print("[ok] Poll created.")
        open_poll(config)
        print("[ok] Poll opened for voting.")
        print(f"[ok] View results at: {config.server_url}/host")
    except RuntimeError as e:
        print(f"[error] Failed to post poll: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
