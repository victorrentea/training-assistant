"""Transcript background loops: timestamp appender and normalizer runner."""

import os
import re
import time
from datetime import datetime
from pathlib import Path

from daemon import log
from daemon.transcript.timestamps import append_empty_line_then_timestamp, infer_template_from_first_line
from daemon.transcript.normalizer import normalize_folder_incremental

_TIMESTAMP_INTERVAL_SECONDS = float(os.environ.get("TRANSCRIPT_TIMESTAMP_INTERVAL_SECONDS", "3"))
_NORMALIZER_INTERVAL_SECONDS = float(os.environ.get("TRANSCRIPT_NORMALIZER_INTERVAL_SECONDS", "3"))

# --- LLM pre-filter (easy to remove: delete this block + usage in TranscriptNormalizerRunner) ---
_LLM_CLEAN_ENABLED = os.environ.get("TRANSCRIPT_LLM_CLEAN", "1").strip().lower() not in {
    "0", "false", "no", "off",
}
_LLM_FILTER_STATS: dict[str, float | str | None] = {
    "last_ms": None,
    "provider": None,
}

def _build_llm_line_filter():
    from daemon.transcript.llm_cleaner import clean_line_with_meta
    _LLM_FILTER_STATS["provider"] = "OLLAMA"
    log.info("transcript", "LLM pre-filter enabled (TRANSCRIPT_LLM_CLEAN=1, model: gemma3:4b)")
    def _filter(text: str) -> str | None:
        result, used_llm, elapsed_ms = clean_line_with_meta(text)
        if used_llm:
            _LLM_FILTER_STATS["last_ms"] = elapsed_ms
        return None if result == "[SKIP]" else result
    return _filter

_llm_line_filter = _build_llm_line_filter() if _LLM_CLEAN_ENABLED else None
# -------------------------------------------------------------------------------------------------

_NORMALIZER_ENABLED = os.environ.get("TRANSCRIPT_NORMALIZER_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}


class TranscriptTimestampAppender:
    """Append heartbeat timestamp lines to the latest transcript text file."""

    def __init__(self, folder: Path, interval_seconds: float = _TIMESTAMP_INTERVAL_SECONDS):
        self.folder = folder
        self.interval_seconds = interval_seconds
        self.enabled = False
        self._next_append_at = 0.0
        self._target_file: Path | None = None
        self._template = None
        self._startup_error_logged = False

    def _resolve_target_file(self) -> Path | None:
        if not self.folder.exists() or not self.folder.is_dir():
            return None
        _date_re = re.compile(r"^(\d{8})\s+(\d{4})\b")

        def _sort_key(f: Path):
            m = _date_re.match(f.name)
            return m.group(1) + m.group(2) if m else ""

        txt_files = sorted(
            [f for f in self.folder.iterdir() if f.suffix.lower() == ".txt"],
            key=_sort_key,
        )
        return txt_files[-1] if txt_files else None

    def _log_startup_error_once(self, message: str) -> None:
        if self._startup_error_logged:
            return
        log.error("daemon", message)
        self._startup_error_logged = True

    def start(self) -> None:
        if self.interval_seconds <= 0:
            self._log_startup_error_once(
                "Timestamp appender disabled: INTERVAL_SECONDS must be > 0"
            )
            return

        self._target_file = self._resolve_target_file()
        if self._target_file is None:
            self._log_startup_error_once(
                f"Timestamp appender disabled: no .txt in {self.folder}"
            )
            return

        self._template = infer_template_from_first_line(self._target_file)
        self._next_append_at = time.monotonic()
        self.enabled = True
        log.info("daemon", f"Transcript timestamp appender enabled ({self.interval_seconds:.1f}s) on {self._target_file.name}")

    def tick(self) -> None:
        if not self.enabled:
            return

        now = time.monotonic()
        if now < self._next_append_at:
            return

        try:
            append_empty_line_then_timestamp(self._target_file, self._template)
        except OSError as exc:
            self.enabled = False
            log.error("daemon", f"Timestamp appender stopped: {exc}")
            return

        self._next_append_at = now + self.interval_seconds


class TranscriptNormalizerRunner:
    """Incrementally normalize raw transcripts in TRANSCRIPTION_FOLDER."""

    def __init__(
        self,
        folder: Path,
        interval_seconds: float = _NORMALIZER_INTERVAL_SECONDS,
        enabled: bool = _NORMALIZER_ENABLED,
    ):
        self.folder = folder
        self.interval_seconds = interval_seconds
        self.enabled = enabled
        self._next_run_at = 0.0

    def start(self) -> None:
        if not self.enabled:
            return
        if self.interval_seconds <= 0:
            self.enabled = False
            log.error("transcript", "Normalizer disabled: TRANSCRIPT_NORMALIZER_INTERVAL_SECONDS must be > 0")
            return
        if not self.folder.exists() or not self.folder.is_dir():
            self.enabled = False
            log.error("transcript", f"Normalizer disabled: folder not found: {self.folder}")
            return
        self._next_run_at = time.monotonic()
        offset_file = self.folder / "normalization.offset.txt"
        if offset_file.exists():
            last_offset = datetime.fromtimestamp(offset_file.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        else:
            last_offset = "none"
        log.info(
            "transcript",
            f"Normalizer enabled ({self.interval_seconds:.1f}s) — last offset: {last_offset}",
        )

    def tick(self) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        if now < self._next_run_at:
            return
        try:
            _LLM_FILTER_STATS["last_ms"] = None
            results = normalize_folder_incremental(self.folder, line_pre_filter=_llm_line_filter)
            written = sum(r.written_lines for r in results)
            crude_words = sum(r.raw_words for r in results)
            llm_ms = _LLM_FILTER_STATS.get("last_ms")
            llm_provider = _LLM_FILTER_STATS.get("provider")
            llm_name = str(llm_provider or "").strip()
            if llm_ms is not None:
                crude_part = f"of {crude_words} " if crude_words > 0 else ""
                llm_part = f" ({crude_part}🤖 {llm_ms:.0f}ms{(' ' + llm_name) if llm_name else ''})"
            else:
                llm_part = ""
            if written > 0:
                words = sum(r.written_words for r in results)
                output_files = len({str(p) for r in results for p in r.output_files})
                raw_sources = sum(1 for r in results if r.written_lines > 0)
                preview_words: list[str] = []
                for result in results:
                    if not result.first_words:
                        continue
                    for word in result.first_words.split():
                        if len(preview_words) >= 7:
                            break
                        preview_words.append(word)
                    if len(preview_words) >= 7:
                        break
                preview_part = f" {' '.join(preview_words)} ..." if preview_words else ""
                words_part = f"Transcripted {words} words{llm_part}{preview_part}"
                if output_files == 1 and raw_sources == 1:
                    log.info("transcript", words_part)
                else:
                    log.info(
                        "transcript",
                        f"{words_part} to {output_files} normalized files (from {raw_sources} raw sources)",
                    )
            elif llm_ms is not None:
                log.info("transcript", f"Transcripted 0 words{llm_part} - remove all = noise")
        except Exception as exc:
            log.error("transcript", f"Normalizer error: {exc}")
        finally:
            self._next_run_at = now + self.interval_seconds
