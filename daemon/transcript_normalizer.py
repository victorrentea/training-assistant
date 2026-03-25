"""Incremental transcript normalizer.

Reads only new bytes from a raw transcript file, keeps an offset sidecar file,
and appends normalized lines to per-day files in the same directory.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path


_RAW_TXT_NAME_RE = re.compile(r"^\d{8}\s+\d{4}\b.*\.txt$", re.IGNORECASE)
_FILENAME_DATE_RE = re.compile(r"^(\d{8})\s+(\d{4})\b")

_ABSOLUTE_TS_RE = re.compile(
    r"^\[\s*(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?\s*\]\s*(.*)$"
)
_TIME_ONLY_TS_RE = re.compile(
    r"^\[\s*(\d{1,3}):(\d{2}):(\d{2})(?:\.\d+)?\s*\]\s*(.*)$"
)
_SPEAKER_RE = re.compile(r"^([^:\t\n\r]{1,40}):\s*(.*)$")


@dataclass
class NormalizationState:
    offset: int = 0
    inode: int | None = None
    device: int | None = None
    mtime_ns: int | None = None
    carryover: str = ""
    current_date: str | None = None
    current_hhmm: str | None = None
    current_speaker: str | None = None


@dataclass
class NormalizeResult:
    raw_file: Path
    offset_file: Path
    read_bytes: int
    written_lines: int
    output_files: list[Path]
    reset_offset: bool


def is_raw_transcript_txt(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == ".txt" and _RAW_TXT_NAME_RE.match(path.name) is not None


def find_latest_raw_transcript_file(folder: Path) -> Path | None:
    if not folder.exists() or not folder.is_dir():
        return None

    def _sort_key(path: Path) -> tuple[str, float]:
        match = _FILENAME_DATE_RE.match(path.name)
        if match:
            return (match.group(1) + match.group(2), path.stat().st_mtime)
        return ("", path.stat().st_mtime)

    files = sorted([f for f in folder.iterdir() if is_raw_transcript_txt(f)], key=_sort_key)
    return files[-1] if files else None


def default_offset_file_for(raw_file: Path) -> Path:
    return raw_file.with_suffix(raw_file.suffix + ".offset")


def _raw_file_date(raw_file: Path) -> date | None:
    match = _FILENAME_DATE_RE.match(raw_file.name)
    if not match:
        return None
    ds = match.group(1)
    try:
        return date(int(ds[:4]), int(ds[4:6]), int(ds[6:8]))
    except ValueError:
        return None


def _load_state(offset_file: Path) -> NormalizationState:
    if not offset_file.exists():
        return NormalizationState()

    raw = offset_file.read_text(encoding="utf-8", errors="replace").strip()
    if not raw:
        return NormalizationState()

    # Backward compatibility: plain integer offset
    if raw.isdigit():
        return NormalizationState(offset=int(raw))

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return NormalizationState()

    return NormalizationState(
        offset=int(data.get("offset", 0) or 0),
        inode=data.get("inode"),
        device=data.get("device"),
        mtime_ns=data.get("mtime_ns"),
        carryover=str(data.get("carryover", "") or ""),
        current_date=data.get("current_date"),
        current_hhmm=data.get("current_hhmm"),
        current_speaker=data.get("current_speaker"),
    )


def _save_state(offset_file: Path, state: NormalizationState) -> None:
    offset_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "offset": state.offset,
        "inode": state.inode,
        "device": state.device,
        "mtime_ns": state.mtime_ns,
        "carryover": state.carryover,
        "current_date": state.current_date,
        "current_hhmm": state.current_hhmm,
        "current_speaker": state.current_speaker,
    }
    tmp = offset_file.with_suffix(offset_file.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
    tmp.replace(offset_file)


def _parse_speaker(text: str) -> tuple[str | None, str]:
    match = _SPEAKER_RE.match(text)
    if not match:
        return None, text

    speaker_candidate = match.group(1).strip().replace("\t", " ")
    content = match.group(2).strip()

    if not speaker_candidate:
        return None, text

    words = speaker_candidate.split()
    if len(words) > 3:
        return None, text
    if any(len(w) > 30 for w in words):
        return None, text

    # Keep speaker parsing conservative to avoid accidental captures like "So: ..."
    if len(words) == 1 and len(words[0]) <= 2:
        return None, text

    return speaker_candidate, content


def _append_outputs(output_dir: Path, grouped_lines: dict[str, list[str]]) -> list[Path]:
    written_files: list[Path] = []
    for day_str in sorted(grouped_lines.keys()):
        lines = grouped_lines[day_str]
        if not lines:
            continue
        out = output_dir / f"{day_str} transcription.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as f:
            for line in lines:
                f.write(line)
                f.write("\n")
        written_files.append(out)
    return written_files


def normalize_incremental(
    raw_file: Path,
    offset_file: Path | None = None,
    output_dir: Path | None = None,
) -> NormalizeResult:
    if not raw_file.exists() or not raw_file.is_file():
        raise FileNotFoundError(f"Raw transcript file not found: {raw_file}")

    offset_file = offset_file or default_offset_file_for(raw_file)
    output_dir = output_dir or raw_file.parent
    state = _load_state(offset_file)

    stat = raw_file.stat()
    current_inode = int(stat.st_ino)
    current_device = int(stat.st_dev)
    current_size = int(stat.st_size)
    current_mtime_ns = int(stat.st_mtime_ns)

    should_reset = False
    if state.offset > current_size:
        should_reset = True
    if state.inode is not None and state.device is not None:
        if state.inode != current_inode or state.device != current_device:
            should_reset = True
    if (
        state.mtime_ns is not None
        and current_mtime_ns > state.mtime_ns
        and current_size == state.offset
        and state.offset > 0
    ):
        # Raw transcript files are append-only; same-size rewrites usually mean restart/rotation.
        should_reset = True

    if should_reset:
        state = NormalizationState()

    with raw_file.open("rb") as f:
        f.seek(state.offset)
        new_bytes = f.read()

    read_bytes = len(new_bytes)
    state.offset += read_bytes
    state.inode = current_inode
    state.device = current_device
    state.mtime_ns = current_mtime_ns

    decoded_chunk = new_bytes.decode("utf-8", errors="replace")
    text = state.carryover + decoded_chunk

    if not text:
        _save_state(offset_file, state)
        return NormalizeResult(raw_file, offset_file, 0, 0, [], should_reset)

    if text.endswith("\n") or text.endswith("\r"):
        complete_lines = text.splitlines()
        state.carryover = ""
    else:
        lines = text.splitlines()
        if lines:
            state.carryover = lines[-1]
            complete_lines = lines[:-1]
        else:
            state.carryover = text
            complete_lines = []

    file_day = _raw_file_date(raw_file)
    grouped: dict[str, list[str]] = {}

    for line in complete_lines:
        stripped = line.strip()
        if not stripped:
            continue

        payload = stripped

        abs_match = _ABSOLUTE_TS_RE.match(stripped)
        if abs_match:
            y, mo, d = int(abs_match.group(1)), int(abs_match.group(2)), int(abs_match.group(3))
            hh, mm = int(abs_match.group(4)), int(abs_match.group(5))
            state.current_date = f"{y:04d}-{mo:02d}-{d:02d}"
            state.current_hhmm = f"{hh:02d}:{mm:02d}"
            payload = abs_match.group(7).strip()
        else:
            time_match = _TIME_ONLY_TS_RE.match(stripped)
            if time_match:
                hh = int(time_match.group(1))
                mm = int(time_match.group(2))
                payload = time_match.group(4).strip()
                # Relative/malformed timestamps do not override an already-known valid clock.
                if state.current_hhmm is None and state.current_date is None and file_day and 0 <= hh <= 23:
                    state.current_date = file_day.isoformat()
                    state.current_hhmm = f"{hh:02d}:{mm:02d}"

        if not payload:
            continue

        explicit_speaker, content = _parse_speaker(payload)
        if explicit_speaker is not None:
            state.current_speaker = explicit_speaker
            text_content = content.strip()
        else:
            text_content = payload.strip()

        if not text_content:
            continue

        speaker = state.current_speaker or "Unknown"

        if state.current_date is None:
            if file_day is None:
                continue
            state.current_date = file_day.isoformat()
        if state.current_hhmm is None:
            state.current_hhmm = "00:00"

        normalized = f"[{state.current_hhmm}] {speaker}: {text_content}"
        grouped.setdefault(state.current_date, []).append(normalized)

    written_files = _append_outputs(output_dir, grouped)
    total_lines = sum(len(v) for v in grouped.values())

    _save_state(offset_file, state)
    return NormalizeResult(raw_file, offset_file, read_bytes, total_lines, written_files, should_reset)


def normalize_latest_in_folder(folder: Path) -> NormalizeResult | None:
    raw_file = find_latest_raw_transcript_file(folder)
    if raw_file is None:
        return None
    return normalize_incremental(raw_file)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Incremental transcript normalizer")
    parser.add_argument("--raw-file", type=Path, help="Path to raw transcript .txt file")
    parser.add_argument(
        "--folder",
        type=Path,
        default=Path(os.environ.get("TRANSCRIPTION_FOLDER", "/Users/victorrentea/Documents/transcriptions")),
        help="Folder containing raw transcripts (used when --raw-file is omitted)",
    )
    parser.add_argument("--offset-file", type=Path, help="Override default .txt.offset sidecar")
    parser.add_argument("--output-dir", type=Path, help="Override output folder for normalized files")
    parser.add_argument("--loop", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=float, default=5.0, help="Loop interval in seconds")
    return parser


def _run_once(args: argparse.Namespace) -> int:
    if args.raw_file:
        result = normalize_incremental(args.raw_file, offset_file=args.offset_file, output_dir=args.output_dir)
    else:
        result = normalize_latest_in_folder(args.folder)

    if result is None:
        print("No raw transcript file found.")
        return 0

    outputs = ", ".join(str(p.name) for p in result.output_files) if result.output_files else "-"
    print(
        f"raw={result.raw_file.name} read_bytes={result.read_bytes} "
        f"written_lines={result.written_lines} reset={str(result.reset_offset).lower()} outputs={outputs}"
    )
    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if not args.loop:
        return _run_once(args)

    if args.interval <= 0:
        print("--interval must be > 0")
        return 2

    while True:
        _run_once(args)
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
