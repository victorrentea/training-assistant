"""Transcript background loops: normalizer runner."""

import os
import re
import socket
import time
from datetime import datetime
from pathlib import Path

from daemon import log
from daemon.transcript.normalizer import normalize_folder_incremental

_NORMALIZER_INTERVAL_SECONDS = float(os.environ.get("TRANSCRIPT_NORMALIZER_INTERVAL_SECONDS", "3"))

# --- LLM pre-filter (easy to remove: delete this block + usage in TranscriptNormalizerRunner) ---
_LLM_CLEAN_ENABLED = os.environ.get("TRANSCRIPT_LLM_CLEAN", "1").strip().lower() not in {
    "0", "false", "no", "off",
}
_LLM_TIMEOUT_SECONDS = int(os.environ.get("TRANSCRIPT_LLM_TIMEOUT_SECONDS", "3"))
_LLM_FILTER_STATS: dict[str, float | str | None] = {
    "last_ms": None,
    "provider": None,
}
_PREVIEW_LEADING_TS_RE = re.compile(r"^\[\s*\d{1,4}:\d{2}:\d{2}(?:\.\d+)?\s*\]\s*")
_llm_last_error_logged_at: float = 0.0
_llm_circuit_open_until: float = 0.0   # circuit breaker: skip LLM until this monotonic time

_LLM_CIRCUIT_COOLDOWN_SECONDS = 60.0   # how long to bypass LLM after a failure

def _build_llm_line_filter():
    from daemon.transcript.llm_cleaner import clean_line_with_meta
    _LLM_FILTER_STATS["provider"] = "OLLAMA"
    log.info("transcript", "LLM pre-filter enabled (TRANSCRIPT_LLM_CLEAN=1, model: gemma3:4b)")
    def _filter(text: str) -> str | None:
        global _llm_last_error_logged_at, _llm_circuit_open_until
        now = time.monotonic()
        if now < _llm_circuit_open_until:
            return text  # circuit open: bypass LLM, write as-is immediately
        try:
            result, used_llm, elapsed_ms = clean_line_with_meta(text, timeout=_LLM_TIMEOUT_SECONDS)
        except Exception as exc:
            _llm_circuit_open_until = now + _LLM_CIRCUIT_COOLDOWN_SECONDS
            if now - _llm_last_error_logged_at >= _LLM_CIRCUIT_COOLDOWN_SECONDS:
                _llm_last_error_logged_at = now
                if isinstance(exc, (TimeoutError, socket.timeout)) or "timed out" in str(exc).lower():
                    log.error("transcript", f"LLM cleaner timed out after {_LLM_TIMEOUT_SECONDS}s — bypassing for {_LLM_CIRCUIT_COOLDOWN_SECONDS:.0f}s")
                else:
                    log.error("transcript", f"LLM cleaner unavailable ({exc}) — bypassing for {_LLM_CIRCUIT_COOLDOWN_SECONDS:.0f}s")
            return text  # fallback: write line without LLM cleanup
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
                    cleaned_preview = _PREVIEW_LEADING_TS_RE.sub("", result.first_words).strip()
                    if not cleaned_preview:
                        continue
                    for word in cleaned_preview.split():
                        if len(preview_words) >= 7:
                            break
                        preview_words.append(word)
                    if len(preview_words) >= 7:
                        break
                base_part = f"Transcripted {words} words{llm_part}"
                preview_part = f": {' '.join(preview_words)} ..." if preview_words else ""
                if output_files == 1 and raw_sources == 1:
                    log.info("transcript", f"{base_part}{preview_part}")
                else:
                    log.info(
                        "transcript",
                        f"{base_part} to {output_files} normalized files (from {raw_sources} raw sources){preview_part}",
                    )
            # elif llm_ms is not None:
            #     log.info("transcript", f"Transcripted 0 words{llm_part} - remove all = noise")
        except Exception as exc:
            log.error("transcript", f"Normalizer error: {exc}")
        finally:
            self._next_run_at = now + self.interval_seconds
