#!/usr/bin/env python3
"""
Shared core library for quiz_generator.py and quiz_daemon.py.
"""

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
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SERVER_URL = "http://localhost:8000"
DEFAULT_MODEL      = "claude-sonnet-4-6"
DEFAULT_MINUTES    = 60
MAX_CHARS_TO_CLAUDE = 60_000
DAEMON_POLL_INTERVAL = 1  # seconds


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
        print("[error] ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)
    if not folder.exists() or not folder.is_dir():
        print(f"[error] Transcription folder not found: {folder}", file=sys.stderr)
        sys.exit(1)
    return Config(
        folder=folder,
        minutes=minutes,
        server_url=os.environ.get("WORKSHOP_SERVER_URL", DEFAULT_SERVER_URL).rstrip("/"),
        api_key=api_key,
        model=os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL),
        dry_run=False,
        host_username=os.environ.get("HOST_USERNAME", "host"),
        host_password=os.environ.get("HOST_PASSWORD", ""),
    )


# ---------------------------------------------------------------------------
# Transcription parsing
# ---------------------------------------------------------------------------

_VTT_TS  = re.compile(r"(?:(\d+):)?(\d{2}):(\d{2})\.(\d{3})\s+-->")
_SRT_TS  = re.compile(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s+-->")
_SRT_SEQ = re.compile(r"^\d+$")
_TXT_TS  = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\.\d+\]\s+[^:]+:\t(.*)")


def _ts_to_seconds(h, m, s) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s)


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


def _parse_txt(text: str) -> list:
    entries = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _TXT_TS.match(line)
        if m:
            entries.append((_ts_to_seconds(m.group(1), m.group(2), m.group(3)), m.group(4).strip()))
        else:
            entries.append((None, line))
    return entries


def load_transcription_files(folder: Path) -> list:
    """Load the most recently modified transcription file from folder."""
    files = sorted(
        [f for f in folder.iterdir() if f.suffix.lower() in {".txt", ".vtt", ".srt"}],
        key=lambda f: f.stat().st_mtime,
    )
    if not files:
        print(f"[error] No .txt, .vtt, or .srt files found in {folder}", file=sys.stderr)
        sys.exit(1)

    latest = files[-1]
    print(f"[info] Using latest transcription: {latest.name}")
    raw = latest.read_text(encoding="utf-8", errors="replace")
    ext = latest.suffix.lower()

    if ext == ".vtt":
        entries = _parse_vtt(raw)
    elif ext == ".srt":
        entries = _parse_srt(raw)
    else:
        entries = _parse_txt(raw)

    print(f"[info]   {latest.name}: {len(entries)} segments")
    return entries


# ---------------------------------------------------------------------------
# Time extraction
# ---------------------------------------------------------------------------

_CHARS_PER_MINUTE = 130 * 5


def extract_last_n_minutes(entries: list, minutes: int) -> str:
    timed = [(ts, txt) for ts, txt in entries if ts is not None]
    if timed:
        max_ts = max(ts for ts, _ in timed)
        cutoff = max_ts - minutes * 60
        text = " ".join(txt for ts, txt in entries if ts is None or ts >= cutoff)
        print(f"[info] Timestamp-based extraction (last {minutes} min, cutoff at {max(0, cutoff/60):.1f} min mark)")
    else:
        budget = minutes * _CHARS_PER_MINUTE
        text = " ".join(txt for _, txt in entries)[-budget:]
        print(f"[info] No timestamps — using last ~{budget:,} chars (≈{minutes} min at 130 wpm)")

    if len(text) > MAX_CHARS_TO_CLAUDE:
        text = text[-MAX_CHARS_TO_CLAUDE:]
        print(f"[info] Text capped at {MAX_CHARS_TO_CLAUDE:,} chars")
    return text.strip()


# ---------------------------------------------------------------------------
# Claude API
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
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        raw = raw.strip()
    return json.loads(raw)


def generate_quiz(text: str, config: Config) -> dict:
    client = anthropic.Anthropic(api_key=config.api_key)
    print(f"[info] Sending {len(text):,} chars to {config.model}...")
    try:
        response = client.messages.create(
            model=config.model, max_tokens=600,
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
        print(f"[error] Claude returned invalid JSON: {e}\n{raw}", file=sys.stderr)
        sys.exit(1)
    _validate_quiz(quiz, raw)
    return quiz


def refine_option(quiz: dict, feedback: str, config: Config) -> dict:
    client = anthropic.Anthropic(api_key=config.api_key)
    current = json.dumps(quiz, indent=2)
    try:
        response = client.messages.create(
            model=config.model, max_tokens=600,
            system=_REFINE_SYSTEM,
            messages=[{"role": "user", "content": f"Current quiz:\n{current}\n\nRequested change: {feedback}"}],
        )
    except anthropic.APIError as e:
        print(f"[error] Claude API error: {e}", file=sys.stderr)
        sys.exit(1)
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
    print()
    print("=" * 60)
    print(f"Q: {quiz['question']}")
    print()
    for i, opt in enumerate(quiz["options"]):
        print(f"  {chr(65 + i)}. {opt}{' ✅' if i in correct else ''}")
    if len(correct) > 1:
        print(f"\n  (multiple expected: {', '.join(chr(65+i) for i in sorted(correct))})")
    print("=" * 60)
    print()


def _quiz_error(msg: str, raw: str) -> None:
    print(f"[error] Invalid quiz format: {msg}\n{raw}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Server HTTP helpers
# ---------------------------------------------------------------------------

def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _post_json(url: str, payload: dict, username: str = "", password: str = "") -> dict:
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if username:
        headers["Authorization"] = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, context=_ssl_context()) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} from {url}: {e.read().decode(errors='replace')}") from e


def _get_json(url: str, username: str = "", password: str = "") -> dict:
    headers = {}
    if username:
        headers["Authorization"] = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, context=_ssl_context()) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} from {url}: {e.read().decode(errors='replace')}") from e


def post_poll(quiz: dict, config: Config) -> None:
    _post_json(f"{config.server_url}/api/poll", {
        "question": quiz["question"],
        "options": quiz["options"],
        "multi": len(quiz.get("correct_indices", [])) > 1,
    }, config.host_username, config.host_password)


def open_poll(config: Config) -> None:
    _post_json(f"{config.server_url}/api/poll/status", {"open": True}, config.host_username, config.host_password)


def post_status(status: str, message: str, config: Config) -> None:
    try:
        _post_json(f"{config.server_url}/api/quiz-status",
                   {"status": status, "message": message},
                   config.host_username, config.host_password)
    except RuntimeError as e:
        print(f"[warn] Could not post status: {e}", file=sys.stderr)



# ---------------------------------------------------------------------------
# Auto-generate (non-interactive, used by daemon)
# ---------------------------------------------------------------------------

def auto_generate(minutes: int, config: Config) -> None:
    """Load transcript → generate quiz → post poll → topic summary → clipboard."""
    post_status("generating", f"Loading transcript (last {minutes} min)…", config)

    entries = load_transcription_files(config.folder)
    if not entries:
        post_status("error", "No transcription files found.", config)
        return

    text = extract_last_n_minutes(entries, minutes)
    if not text:
        post_status("error", "Extracted text is empty.", config)
        return

    post_status("generating", f"Sending {len(text):,} chars to Claude…", config)

    try:
        quiz = generate_quiz(text, config)
    except SystemExit:
        post_status("error", "Claude failed to generate a valid quiz.", config)
        return

    print_quiz(quiz)

    try:
        post_poll(quiz, config)
        open_poll(config)
    except RuntimeError as e:
        post_status("error", f"Failed to post poll: {e}", config)
        return

    post_status("done", "✅ Poll created and opened.", config)
