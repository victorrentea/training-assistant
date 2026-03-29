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
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from daemon.transcript.parser import _parse_speaker, _is_low_signal_noise
from daemon.transcript.writer import _append_outputs, _infer_last_speaker_from_normalized


_RAW_TXT_NAME_RE = re.compile(r"^\d{8}\s+\d{4}\b.*\.txt$", re.IGNORECASE)
_FILENAME_DATE_RE = re.compile(r"^(\d{8})\s+(\d{4})\b")

_ABSOLUTE_TS_RE = re.compile(
    r"^\[\s*(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?\s*\]\s*(.*)$"
)
_TIME_ONLY_TS_RE = re.compile(
    r"^\[\s*(\d{1,3}):(\d{2}):(\d{2})(?:\.\d+)?\s*\]\s*(.*)$"
)


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
    raw_words: int = 0
    written_words: int = 0
    first_words: str = ""


def _legacy_offset_file_for(raw_file: Path) -> Path:
    return raw_file.with_suffix(raw_file.suffix + ".offset")


def _list_raw_files_sorted(folder: Path) -> list[Path]:
    def _sort_key(path: Path) -> tuple[str, float]:
        match = _FILENAME_DATE_RE.match(path.name)
        if match:
            return (match.group(1) + match.group(2), path.stat().st_mtime)
        return ("", path.stat().st_mtime)

    return sorted([f for f in folder.iterdir() if is_raw_transcript_txt(f)], key=_sort_key)


def is_raw_transcript_txt(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == ".txt" and _RAW_TXT_NAME_RE.match(path.name) is not None


def default_offset_file_for(raw_file: Path) -> Path:
    return raw_file.parent / "normalization.offset.txt"


def _raw_file_date(raw_file: Path) -> date | None:
    match = _FILENAME_DATE_RE.match(raw_file.name)
    if not match:
        return None
    ds = match.group(1)
    try:
        return date(int(ds[:4]), int(ds[4:6]), int(ds[6:8]))
    except ValueError:
        return None


def _load_state(offset_file: Path, raw_key: str | None = None) -> NormalizationState:
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

    # New format: one normalization.offset.txt with per-raw-file state map.
    if raw_key and isinstance(data.get("files"), dict):
        item = data["files"].get(raw_key)
        if not isinstance(item, dict):
            return NormalizationState()
        data = item

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


def _save_state(offset_file: Path, state: NormalizationState, raw_key: str | None = None) -> None:
    offset_file.parent.mkdir(parents=True, exist_ok=True)
    state_payload = {
        "offset": state.offset,
        "inode": state.inode,
        "device": state.device,
        "mtime_ns": state.mtime_ns,
        "carryover": state.carryover,
        "current_date": state.current_date,
        "current_hhmm": state.current_hhmm,
        "current_speaker": state.current_speaker,
    }
    payload = state_payload
    if raw_key:
        existing: dict = {}
        if offset_file.exists():
            try:
                existing = json.loads(offset_file.read_text(encoding="utf-8", errors="replace"))
            except json.JSONDecodeError:
                existing = {}
        files_map = existing.get("files") if isinstance(existing, dict) else None
        if not isinstance(files_map, dict):
            files_map = {}
        files_map[raw_key] = state_payload
        payload = {"version": 1, "files": files_map}
    tmp = offset_file.with_suffix(offset_file.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
    tmp.replace(offset_file)


def _has_state_for_raw(offset_file: Path, raw_key: str) -> bool:
    if not offset_file.exists():
        return False
    raw = offset_file.read_text(encoding="utf-8", errors="replace").strip()
    if not raw:
        return False
    if raw.isdigit():
        return True
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False
    files_map = data.get("files") if isinstance(data, dict) else None
    if isinstance(files_map, dict):
        return raw_key in files_map
    return isinstance(data, dict) and "offset" in data


def normalize_incremental(
    raw_file: Path,
    offset_file: Path | None = None,
    output_dir: Path | None = None,
    now: datetime | None = None,
    line_pre_filter: "Callable[[str], str | None] | None" = None,
) -> NormalizeResult:
    if not raw_file.exists() or not raw_file.is_file():
        raise FileNotFoundError(f"Raw transcript file not found: {raw_file}")

    if offset_file is None:
        offset_file = default_offset_file_for(raw_file)
    output_dir = output_dir or raw_file.parent
    poll_now = now or datetime.now()
    poll_hhmm = poll_now.strftime("%H:%M")
    poll_day = poll_now.date().isoformat()
    raw_key = raw_file.name
    state = _load_state(offset_file, raw_key=raw_key)
    if state.offset == 0 and not offset_file.exists():
        legacy = _legacy_offset_file_for(raw_file)
        if legacy.exists():
            state = _load_state(legacy)

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
        _save_state(offset_file, state, raw_key=raw_key)
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
    default_output_day = file_day.isoformat() if file_day else (state.current_date or poll_day)
    if state.current_speaker is None:
        normalized_output_file = output_dir / f"{default_output_day} transcription.txt"
        state.current_speaker = _infer_last_speaker_from_normalized(normalized_output_file)
    if state.current_date is None:
        state.current_date = default_output_day
    state.current_hhmm = poll_hhmm
    grouped: dict[str, list[str]] = {}
    raw_words = 0
    total_words = 0
    first_words: list[str] = []

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
        raw_words += len(text_content.split())
        if _is_low_signal_noise(text_content):
            continue
        # --- LLM pre-filter (optional, easy to remove) ---
        if line_pre_filter is not None:
            text_content = line_pre_filter(text_content)
            if not text_content:
                continue
        # --------------------------------------------------

        speaker = state.current_speaker or "Unknown"
        line_day = state.current_date or default_output_day
        normalized = f"[{poll_hhmm}] {speaker}: {text_content}"
        grouped.setdefault(line_day, []).append(normalized)
        words = text_content.split()
        total_words += len(words)
        if len(first_words) < 10:
            first_words.extend(words[: 10 - len(first_words)])

    written_files = _append_outputs(output_dir, grouped)
    total_lines = sum(len(v) for v in grouped.values())

    _save_state(offset_file, state, raw_key=raw_key)
    return NormalizeResult(
        raw_file,
        offset_file,
        read_bytes,
        total_lines,
        written_files,
        should_reset,
        raw_words,
        total_words,
        " ".join(first_words),
    )


def normalize_folder_incremental(
    folder: Path,
    now: datetime | None = None,
    line_pre_filter: "Callable[[str], str | None] | None" = None,
) -> list[NormalizeResult]:
    """Normalize all relevant raw files in folder.

    Policy:
    - Always process latest raw file.
    - Also process any older raw file that already has a .offset sidecar
      (to flush remaining lines after day/file rollover).
    """
    if not folder.exists() or not folder.is_dir():
        return []

    files = _list_raw_files_sorted(folder)
    if not files:
        return []

    latest = files[-1]
    candidates: list[Path] = []
    for raw in files:
        shared_offset = default_offset_file_for(raw)
        legacy_offset = _legacy_offset_file_for(raw)
        if raw == latest or _has_state_for_raw(shared_offset, raw.name) or legacy_offset.exists():
            candidates.append(raw)

    results: list[NormalizeResult] = []
    for raw in candidates:
        results.append(normalize_incremental(raw, now=now, line_pre_filter=line_pre_filter))
    return results


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
        result = normalize_incremental(
            args.raw_file,
            offset_file=args.offset_file,
            output_dir=args.output_dir,
        )
        results = [result]
    else:
        results = normalize_folder_incremental(args.folder)

    if not results:
        print("No raw transcript file found.")
        return 0

    for result in results:
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
