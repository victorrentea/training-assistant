"""
Offline LLM-based pre-cleaner for raw Whisper transcription files.

Sends each content line to a local Ollama model and asks it to either:
  - Return the cleaned line (real speech, possibly with repetitions removed)
  - Return [SKIP] (Whisper hallucination during silence)

Usage:
    python3 -m daemon.transcript.llm_cleaner <input_file> <output_file>
    python3 -m daemon.transcript.llm_cleaner <input_file>   # writes to <input_file>.cleaned.txt

This is a standalone tool — it does NOT modify any existing normalizer or pipeline code.
Run it offline to pre-clean raw files before normalization.
"""
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "gemma3:4b"

SYSTEM_PROMPT = """\
You are a transcript cleaner for a software trainer's speech-to-text recordings.
The trainer speaks Romanian and English, mixing both languages naturally.
The speech-to-text tool (Whisper) often hallucinates garbage when there is silence or background noise.

Your job: given one transcript line, output either the cleaned line or [SKIP].

OUTPUT RULES (strict):
- Output only the cleaned line, or exactly [SKIP]. Nothing else.
- Keep the timestamp prefix (e.g. "[ 2026-03-26 14:27:05.00 ]") unchanged if present.
- Do not add explanations or blank lines.

ALWAYS output [SKIP] for these Whisper hallucination patterns:
1. Any text containing Chinese, Japanese, Korean, Cyrillic, Arabic, or other non-Latin/Romanian scripts
2. YouTube/social media boilerplate: "subscribe", "like and comment", "Thanks for watching", \
"don't forget to", "follow me", "new video every", "New HD video"
3. Recipe or cooking instructions: ingredient lists like "1/2 tsp", "1/4 cup", "mix well", "bake at"
4. Generic hardware/software tutorial boilerplate: "disconnect the power cord", "press START/STOP", \
"Go to File > Place Embedded", "click on the file you want to save"
5. A single word or short phrase (under 8 words) repeated 5 or more times consecutively
6. Strings of repeated characters like "e-e-e-e-e-e" or "r-r-r-r-r-r"
7. URLs combined with promotional text

KEEP and lightly clean real speech:
- Romanian or English sentences that make sense in a software development context
- Trainer instructions to an AI coding assistant ("vreau să...", "I want you to...", "find the file...")
- Technical questions or explanations about code, Java, Spring, daemons, APIs, etc.
- If a real sentence is repeated 2-3 times, keep only one copy
- Fix obvious transcription errors (missing diacritics, run-together words) but preserve \
technical terms, tool names, and library names exactly as spoken

EXAMPLES:
Input:  [ 14:27:05 ]  Reține că am railway instalat, CLI.
Output: [ 14:27:05 ]  Reține că am railway instalat, CLI.

Input:  [ 14:30:50 ]  If you have any questions please ask. If you have any questions please ask. If you have any questions please ask.
Output: [ 14:30:50 ]  If you have any questions please ask.

Input:  [ 14:37:34 ]  Disconnect the power cord from the main board. Thanks for watching and don't forget to like and subscribe!
Output: [SKIP]

Input:  [ 14:35:46 ]  Război, război, război, război, război, război, război, război, război, război,
Output: [SKIP]

Input:  [ 14:37:58 ]  1/2 茶 (4g)  1/2 茶 (4g)  1/2 茶 (4g)
Output: [SKIP]

Input:  [ 14:40:15 ]  真を見るためにスマートフォンを使用して字幕を作成する必要があります。
Output: [SKIP]

Input:  [ 14:38:22 ]  Vreau sa va arat ca daemon trebuie sa faci push pe master.
Output: [ 14:38:22 ]  Vreau să vă arăt că daemon-ul trebuie să faci push pe master.
"""

# Lines that are obviously empty / timestamp-only — skip LLM entirely
_EMPTY_LINE_RE = re.compile(r"^\[\s*[\d\-: .]+\s*\]\s*$")

# Non-Latin scripts: CJK, Cyrillic, Arabic, Hebrew, Thai, Korean, etc.
_NON_LATIN_RE = re.compile(r"[\u0400-\u04FF\u0600-\u06FF\u4E00-\u9FFF\u3040-\u30FF\uAC00-\uD7AF\u0E00-\u0E7F]")

# Recipe measurement pattern: "1/2 tsp", "3/4 cup", "1/4 g", etc.
_RECIPE_MEASURE_RE = re.compile(r"\b\d+/\d+\s*(tsp|tbsp|cup|g|ml|oz|lb|kg|mg)\b", re.IGNORECASE)

# A single token (word) repeated 5+ times
_REPEATED_WORD_RE = re.compile(r"\b(\w{2,})\b(?:[,.\s]+\1\b){4,}", re.IGNORECASE)


def is_deterministic_garbage(text: str) -> bool:
    """
    Fast regex-based check for patterns that are unambiguously Whisper hallucinations.
    Returns True if the line should be skipped without calling the LLM.
    """
    if _NON_LATIN_RE.search(text):
        return True
    if _RECIPE_MEASURE_RE.search(text):
        return True
    if _REPEATED_WORD_RE.search(text):
        return True
    return False


def is_content_line(line: str) -> bool:
    """True if the line has text content beyond just a timestamp."""
    stripped = line.strip()
    if not stripped:
        return False
    if _EMPTY_LINE_RE.match(stripped):
        return False
    return True


def clean_line(line: str, model: str = MODEL, url: str = OLLAMA_URL, timeout: int = 30) -> str:
    """
    Clean one transcript line. Returns the cleaned text or '[SKIP]'.
    Deterministic pre-filter runs first; LLM only called for ambiguous lines.
    """
    # Strip timestamp prefix for the content check
    content = re.sub(r"^\[\s*[\d\-: .]+\s*\]\s*", "", line.strip())
    if is_deterministic_garbage(content):
        return "[SKIP]"
    return call_ollama(line, model=model, url=url, timeout=timeout)


def clean_line_with_meta(
    line: str,
    model: str = MODEL,
    url: str = OLLAMA_URL,
    timeout: int = 30,
) -> tuple[str, bool, float]:
    """
    Clean one transcript line and return metadata.

    Returns:
      - cleaned text or '[SKIP]'
      - whether a local LLM call was made
      - local LLM duration in ms (0 when no LLM call was made)
    """
    content = re.sub(r"^\[\s*[\d\-: .]+\s*\]\s*", "", line.strip())
    if is_deterministic_garbage(content):
        return "[SKIP]", False, 0.0

    started_at = time.perf_counter()
    result = call_ollama(line, model=model, url=url, timeout=timeout)
    elapsed_ms = (time.perf_counter() - started_at) * 1000.0
    return result, True, elapsed_ms


def call_ollama(line: str, model: str = MODEL, url: str = OLLAMA_URL, timeout: int = 30) -> str:
    """Send one line to Ollama. Returns cleaned line text or '[SKIP]'."""
    payload = {
        "model": model,
        "system": SYSTEM_PROMPT,
        "prompt": line.strip(),
        "stream": False,
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())["response"].strip()


def clean_file(
    input_path: str | Path,
    output_path: str | Path,
    model: str = MODEL,
    ollama_url: str = OLLAMA_URL,
    progress: bool = True,
) -> dict:
    """
    Read a raw transcription file, clean each content line via LLM, write result.

    Empty/timestamp-only lines are passed through unchanged (they carry timing info
    that the normalizer needs).

    Returns stats: {total, content, kept, skipped, errors}
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    lines = input_path.read_text(encoding="utf-8").splitlines(keepends=True)
    stats = {"total": len(lines), "content": 0, "kept": 0, "skipped": 0, "errors": 0}

    out_lines = []
    for i, line in enumerate(lines):
        if not is_content_line(line):
            out_lines.append(line)
            continue

        stats["content"] += 1
        try:
            result = clean_line(line.strip(), model=model, url=ollama_url)
        except Exception as e:
            # On error, keep the original line (safe fallback)
            stats["errors"] += 1
            out_lines.append(line)
            if progress:
                print(f"  [ERROR] line {i+1}: {e}", file=sys.stderr)
            continue

        if result == "[SKIP]":
            stats["skipped"] += 1
            if progress:
                print(f"  SKIP  [{i+1:5d}] {line.strip()[:80]}", file=sys.stderr)
        else:
            stats["kept"] += 1
            # Preserve original line ending
            ending = "\n" if line.endswith("\n") else ""
            out_lines.append(result + ending)

    output_path.write_text("".join(out_lines), encoding="utf-8")
    return stats


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 -m daemon.transcript.llm_cleaner <input_file> [output_file]")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else input_path.with_suffix(".cleaned.txt")

    print(f"Cleaning: {input_path}")
    print(f"Output:   {output_path}")

    stats = clean_file(input_path, output_path, progress=True)

    print(f"\nDone.")
    print(f"  Total lines  : {stats['total']}")
    print(f"  Content lines: {stats['content']}")
    print(f"  Kept         : {stats['kept']}")
    print(f"  Skipped      : {stats['skipped']}")
    print(f"  Errors       : {stats['errors']}")
    if stats["content"]:
        pct = stats["skipped"] / stats["content"] * 100
        print(f"  Garbage rate : {pct:.0f}%")


if __name__ == "__main__":
    main()
