#!/usr/bin/env python3
"""
Live dual-channel transcription prototype.
Uses mlx-whisper (Apple Silicon Metal GPU) + sounddevice.

Install deps first:
    pip3 install mlx-whisper sounddevice numpy

Usage:
    python3 wispr-addons/transcribe.py                          # interactive device picker
    python3 wispr-addons/transcribe.py --list-devices           # list audio devices
    python3 wispr-addons/transcribe.py --me 0 --audience 5      # specify device indices directly
    python3 wispr-addons/transcribe.py --me 0 --no-audience     # only capture "me" channel

Output:
    [me      ] Deci, hai să vorbim despre design patterns.
    [audience] Can you explain the factory pattern?

Model: mlx-community/whisper-large-v3
  - ~6-8s latency per chunk
  - Auto-detects Romanian / English per chunk
  - Runs fully on Apple Silicon GPU (no internet needed after first download)
"""

import argparse
import contextlib
import os
import queue
import sys
import threading
import time
from datetime import datetime

import numpy as np

# ── Config ────────────────────────────────────────────────────────────────────
SAMPLE_RATE = 16000           # Whisper expects 16kHz mono
CHUNK_SECONDS = 4             # audio chunk size sent to Whisper (seconds)
OVERLAP_SECONDS = 0.5         # overlap between chunks to avoid cutting words
SILENCE_RMS_THRESHOLD = 0.018 # skip transcription if chunk is below this RMS
MODEL = "mlx-community/whisper-large-v3-mlx"

# Whisper hallucinations to suppress (common on near-silence)
HALLUCINATIONS = {
    "thank you.", "thanks for watching.", "thanks.", "you", ".",
    "subtitles by the amara.org community", "www.mooji.org",
    "[music]", "[ music ]", "(music)", "♪", "...",
}


# ── Audio capture ─────────────────────────────────────────────────────────────
class ChannelCapture:
    """Captures audio from one device and pushes chunks to a shared queue."""

    def __init__(self, device, label: str, tx_queue: queue.Queue):
        self.device = device
        self.label = label
        self.tx_queue = tx_queue
        self._buffer = np.zeros(0, dtype=np.float32)
        self._chunk_samples = int(SAMPLE_RATE * CHUNK_SECONDS)
        self._overlap_samples = int(SAMPLE_RATE * OVERLAP_SECONDS)
        self._stream = None

    def start(self):
        """Start capture in a background thread that auto-restarts on device errors."""
        self._running = True
        threading.Thread(target=self._capture_loop, daemon=True).start()

    def stop(self):
        self._running = False

    def _open_stream(self):
        import sounddevice as sd
        stream = sd.InputStream(
            device=self.device,
            channels=1,
            samplerate=SAMPLE_RATE,
            dtype="float32",
            blocksize=int(SAMPLE_RATE * 0.1),
            callback=self._callback,
        )
        stream.start()
        return stream

    def _capture_loop(self):
        """Keep the stream alive; restart on CoreAudio / device errors."""
        while self._running:
            try:
                stream = self._open_stream()
                print(f"  ✓ [{self.label:<8}] capturing from device {self.device!r}")
                while self._running and stream.active:
                    time.sleep(0.5)
                stream.stop()
                stream.close()
                if self._running:
                    print(f"  ↻ [{self.label:<8}] stream ended, restarting...", file=sys.stderr)
            except Exception as e:
                print(f"  ✗ [{self.label:<8}] stream error: {e} — retrying in 2s", file=sys.stderr)
                time.sleep(2)

    def _callback(self, indata, frames, time_info, status):
        mono = indata[:, 0]
        self._buffer = np.concatenate([self._buffer, mono])

        while len(self._buffer) >= self._chunk_samples:
            chunk = self._buffer[: self._chunk_samples].copy()
            # keep overlap for next iteration so words aren't cut at boundaries
            self._buffer = self._buffer[self._chunk_samples - self._overlap_samples :]

            rms = float(np.sqrt(np.mean(chunk ** 2)))
            if rms >= SILENCE_RMS_THRESHOLD:
                self.tx_queue.put((self.label, chunk, rms))


# ── Transcription worker ──────────────────────────────────────────────────────
def _transcribe(audio, model: str, language: str | None = None) -> dict:
    """Run mlx_whisper with all output suppressed."""
    import mlx_whisper
    with open(os.devnull, "w") as devnull, \
         contextlib.redirect_stdout(devnull), \
         contextlib.redirect_stderr(devnull):
        return mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=model,
            language=language,
            verbose=False,
            condition_on_previous_text=False,
        )


def transcriber_loop(tx_queue: queue.Queue, model: str):
    """Single thread — serialises GPU usage so both channels share the model."""
    import mlx_whisper

    print(f"\nLoading model: {model}")
    print("(first run downloads ~3 GB — this may take a few minutes...)\n")
    # Warm-up: trigger model download/load with visible output (1s of silence)
    mlx_whisper.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), path_or_hf_repo=model, verbose=False)
    print("Model ready. Transcribing...\n")

    while True:
        try:
            label, audio, rms = tx_queue.get(timeout=1)
        except queue.Empty:
            continue

        try:
            result = _transcribe(audio, model)
            text = result.get("text", "").strip()
            lang = result.get("language", "?")

            # If Whisper guessed a language other than ro/en, re-run forced to Romanian
            # (Romanian shares many sounds with other Latin/Slavic languages and gets misidentified)
            if lang not in ("ro", "en"):
                result = _transcribe(audio, model, language="ro")
                text = result.get("text", "").strip()
                lang = "ro"

            if not text or text.lower() in HALLUCINATIONS:
                continue

            ts = datetime.now().strftime("%H:%M:%S")
            print(f"{ts}  [{label:<8}]  ({lang})  {text}")

        except Exception as e:
            print(f"[transcriber error] {e}", file=sys.stderr)


# ── Device listing ────────────────────────────────────────────────────────────
def list_devices():
    import sounddevice as sd
    devs = sd.query_devices()
    print("\nAvailable audio input devices:\n")
    print(f"  {'idx':>3}  {'name':<45}  {'ch':>3}  {'rate':>6}")
    print("  " + "-" * 65)
    for i, d in enumerate(devs):
        if d["max_input_channels"] > 0:
            print(f"  {i:>3}  {d['name']:<45}  {d['max_input_channels']:>3}  {int(d['default_samplerate']):>6}")
    print()


def pick_device(prompt: str) -> int | None:
    while True:
        raw = input(prompt).strip()
        if raw.lower() in ("n", "no", "none", "-"):
            return None
        try:
            return int(raw)
        except ValueError:
            print("  Enter a number (or 'n' to skip).")


def _build_channels(args, tx_queue: queue.Queue) -> list[ChannelCapture] | None:
    """Parse CLI args into ChannelCapture instances. Returns None on error."""
    channels: list[ChannelCapture] = []
    if args.channels:
        for spec in args.channels:
            try:
                idx_str, label = spec.split(":", 1)
                channels.append(ChannelCapture(int(idx_str), label, tx_queue))
            except ValueError:
                print(f"  Bad --channels spec {spec!r}, expected idx:label", file=sys.stderr)
                return None
    else:
        me_idx = args.me
        if me_idx is None:
            me_idx = pick_device("  Device index for [me] (your mic): ")
        audience_idx = args.audience
        if not args.no_audience and audience_idx is None:
            print("  For Loopback app: look for 'Loopback Audio' or your virtual device above.")
            audience_idx = pick_device("  Device index for [audience] (Loopback virtual device, or 'n' to skip): ")
        if me_idx is not None:
            channels.append(ChannelCapture(me_idx, "me", tx_queue))
        if audience_idx is not None:
            channels.append(ChannelCapture(audience_idx, "audience", tx_queue))

    if not channels:
        print("No channels configured. Exiting.")
        return None
    return channels


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    global CHUNK_SECONDS, SILENCE_RMS_THRESHOLD

    parser = argparse.ArgumentParser(
        description="Live multi-channel Whisper transcription",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
               "  --me 5 --audience 17\n"
               "  --channels 5:xlr 7:macbook 18:tozoom   (compare 3 sources)",
    )
    parser.add_argument("--list-devices", action="store_true", help="Print audio devices and exit")
    parser.add_argument("--me", type=int, default=None, metavar="IDX", help="Device index for 'me' channel")
    parser.add_argument("--audience", type=int, default=None, metavar="IDX", help="Device index for 'audience' channel")
    parser.add_argument("--no-audience", action="store_true", help="Skip audience channel (ignored when --channels used)")
    parser.add_argument("--channels", nargs="+", metavar="IDX:LABEL",
                        help="Explicit channel list, overrides --me/--audience. Format: idx:label")
    parser.add_argument("--model", default=MODEL, help=f"mlx-whisper model (default: {MODEL})")
    parser.add_argument("--chunk", type=float, default=CHUNK_SECONDS, help=f"Chunk size in seconds (default: {CHUNK_SECONDS})")
    parser.add_argument("--threshold", type=float, default=SILENCE_RMS_THRESHOLD, help="RMS silence threshold")
    args = parser.parse_args()

    CHUNK_SECONDS = args.chunk
    SILENCE_RMS_THRESHOLD = args.threshold

    if args.list_devices:
        list_devices()
        return

    list_devices()

    tx_queue: queue.Queue = queue.Queue()
    channels = _build_channels(args, tx_queue)
    if channels is None:
        return

    print("\nStarting capture streams...")
    for ch in channels:
        ch.start()

    worker = threading.Thread(target=transcriber_loop, args=(tx_queue, args.model), daemon=True)
    worker.start()

    print("\nTranscribing... Press Ctrl+C to stop.\n")
    print(f"  Chunk size: {CHUNK_SECONDS}s  |  Silence threshold RMS: {SILENCE_RMS_THRESHOLD}  |  Model: {args.model}\n")

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n\nStopping...")
    finally:
        for ch in channels:
            ch.stop()


if __name__ == "__main__":
    main()
