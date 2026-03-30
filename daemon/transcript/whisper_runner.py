"""Live Whisper transcription runner — writes directly to normalized transcript files.

Activated by setting env vars:
    WHISPER_ME_DEVICE=5        # device index for trainer mic (🎙️TO Zoom = XLR filtered)
    WHISPER_AUDIENCE_DEVICE=17 # device index for audience (FROM Zoom loopback)

Optional:
    WHISPER_ME_SPEAKER=Victor        (default)
    WHISPER_AUDIENCE_SPEAKER=Participant  (default)
    WHISPER_MODEL=mlx-community/whisper-large-v3-mlx  (default)
    WHISPER_CHUNK_SECONDS=4
    WHISPER_SILENCE_THRESHOLD=0.018
"""

import contextlib
import os
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from daemon import log

# ── Config from env ────────────────────────────────────────────────────────────
_ME_DEVICE    = os.environ.get("WHISPER_ME_DEVICE")
_AUD_DEVICE   = os.environ.get("WHISPER_AUDIENCE_DEVICE")
_ME_SPEAKER   = os.environ.get("WHISPER_ME_SPEAKER",       "Victor")
_AUD_SPEAKER  = os.environ.get("WHISPER_AUDIENCE_SPEAKER", "Participant")
_MODEL        = os.environ.get("WHISPER_MODEL",            "mlx-community/whisper-large-v3-mlx")
_CHUNK_SEC    = float(os.environ.get("WHISPER_CHUNK_SECONDS",      "4"))
_OVERLAP_SEC  = float(os.environ.get("WHISPER_OVERLAP_SECONDS",    "0.5"))
_THRESHOLD    = float(os.environ.get("WHISPER_SILENCE_THRESHOLD",  "0.018"))
_SAMPLE_RATE  = 16000

_HALLUCINATIONS = {
    "thank you.", "thanks for watching.", "thanks.", "you", ".",
    "subtitles by the amara.org community", "www.mooji.org",
    "[music]", "[ music ]", "(music)", "♪", "...",
}


# ── Audio capture ──────────────────────────────────────────────────────────────
class _ChannelCapture:
    def __init__(self, device, label: str, tx_queue: queue.Queue):
        self.device  = device
        self.label   = label
        self._queue  = tx_queue
        self._buf    = np.zeros(0, dtype=np.float32)
        self._chunk  = int(_SAMPLE_RATE * _CHUNK_SEC)
        self._overlap = int(_SAMPLE_RATE * _OVERLAP_SEC)
        self._running = False

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False

    def _open(self):
        import sounddevice as sd
        s = sd.InputStream(
            device=self.device, channels=1,
            samplerate=_SAMPLE_RATE, dtype="float32",
            blocksize=int(_SAMPLE_RATE * 0.1),
            callback=self._cb,
        )
        s.start()
        return s

    def _loop(self):
        while self._running:
            try:
                s = self._open()
                log.info("transcript", f"🎙️ [{self.label}] capturing from device {self.device!r}")
                while self._running and s.active:
                    time.sleep(0.5)
                s.stop(); s.close()
                if self._running:
                    log.info("transcript", f"🎙️ [{self.label}] stream ended, restarting...")
            except Exception as exc:
                log.error("transcript", f"🎙️ [{self.label}] stream error: {exc} — retry in 2s")
                time.sleep(2)

    def _cb(self, indata, frames, time_info, status):
        self._buf = np.concatenate([self._buf, indata[:, 0]])
        while len(self._buf) >= self._chunk:
            chunk = self._buf[: self._chunk].copy()
            self._buf = self._buf[self._chunk - self._overlap :]
            rms = float(np.sqrt(np.mean(chunk ** 2)))
            if rms >= _THRESHOLD:
                self._queue.put((self.label, chunk))


# ── Transcription thread ───────────────────────────────────────────────────────
def _transcribe(audio, language=None):
    import mlx_whisper
    with open(os.devnull, "w") as dev, \
         contextlib.redirect_stdout(dev), \
         contextlib.redirect_stderr(dev):
        return mlx_whisper.transcribe(
            audio, path_or_hf_repo=_MODEL,
            language=language, verbose=False,
            condition_on_previous_text=False,
        )


def _transcriber_loop(tx_queue: queue.Queue, on_segment):
    import mlx_whisper
    log.info("transcript", f"🎙️ Loading Whisper model: {_MODEL} ...")
    mlx_whisper.transcribe(
        np.zeros(_SAMPLE_RATE, dtype=np.float32),
        path_or_hf_repo=_MODEL, verbose=False,
    )
    log.info("transcript", "🎙️ Whisper model ready — live transcription active")

    while True:
        try:
            label, audio = tx_queue.get(timeout=1)
        except queue.Empty:
            continue
        try:
            result = _transcribe(audio)
            text = result.get("text", "").strip()
            lang = result.get("language", "?")
            if lang not in ("ro", "en"):
                result = _transcribe(audio, language="ro")
                text   = result.get("text", "").strip()
                lang   = "ro"
            if not text or text.lower() in _HALLUCINATIONS:
                continue
            on_segment(label, lang, text)
        except Exception as exc:
            log.error("transcript", f"🎙️ Whisper error: {exc}")


# ── Runner ─────────────────────────────────────────────────────────────────────
class WhisperTranscriptionRunner:
    """Starts Whisper capture threads and writes segments to normalized files."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.enabled    = False
        self._channels: list[_ChannelCapture] = []

    def start(self):
        me_idx  = int(_ME_DEVICE)  if _ME_DEVICE  else None
        aud_idx = int(_AUD_DEVICE) if _AUD_DEVICE else None

        if me_idx is None and aud_idx is None:
            log.info("transcript", "🎙️ Whisper disabled — set WHISPER_ME_DEVICE / WHISPER_AUDIENCE_DEVICE to enable")
            return

        tx_queue: queue.Queue = queue.Queue()
        if me_idx  is not None:
            self._channels.append(_ChannelCapture(me_idx,  _ME_SPEAKER,  tx_queue))
        if aud_idx is not None:
            self._channels.append(_ChannelCapture(aud_idx, _AUD_SPEAKER, tx_queue))

        for ch in self._channels:
            ch.start()

        threading.Thread(
            target=_transcriber_loop,
            args=(tx_queue, self._on_segment),
            daemon=True,
        ).start()

        self.enabled = True

    def stop(self):
        for ch in self._channels:
            ch.stop()

    def _on_segment(self, label: str, lang: str, text: str):
        now     = datetime.now()
        hhmm    = now.strftime("%H:%M")
        day_str = now.strftime("%Y-%m-%d")
        line    = f"[{hhmm}] {label}: {text}"

        out_file = self.output_dir / f"{day_str} transcription.txt"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        with out_file.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

        words   = len(text.split())
        preview = " ".join(text.split()[:8])
        dots    = " ..." if len(text.split()) > 8 else ""
        log.info("transcript", f"🎙️Transcripted {words} words: {preview}{dots}")
