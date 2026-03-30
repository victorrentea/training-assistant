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

Model: mlx-community/whisper-large-v3-turbo
  - ~3-5s latency per chunk
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
SILENCE_RMS_THRESHOLD = 0.012 # skip transcription if chunk is below this RMS
MODEL = "mlx-community/whisper-large-v3-turbo"

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
        import sounddevice as sd
        self._stream = sd.InputStream(
            device=self.device,
            channels=1,
            samplerate=SAMPLE_RATE,
            dtype="float32",
            blocksize=int(SAMPLE_RATE * 0.1),   # 100ms callback blocks
            callback=self._callback,
        )
        self._stream.start()
        print(f"  ✓ [{self.label:<8}] capturing from device {self.device!r}")

    def stop(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()

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
def transcriber_loop(tx_queue: queue.Queue, model: str):
    """Single thread — serialises GPU usage so both channels share the model."""
    import mlx_whisper

    print(f"\nLoading model: {model}")
    print("(first run downloads ~800 MB — subsequent runs are instant)\n")

    while True:
        try:
            label, audio, rms = tx_queue.get(timeout=1)
        except queue.Empty:
            continue

        try:
            with open(os.devnull, "w") as devnull, \
                 contextlib.redirect_stdout(devnull), \
                 contextlib.redirect_stderr(devnull):
                result = mlx_whisper.transcribe(
                    audio,
                    path_or_hf_repo=model,
                    # no language= → auto-detect per chunk (Romanian + English)
                    verbose=False,
                    condition_on_previous_text=False,  # avoid hallucination snowball
                )
            text = result.get("text", "").strip()
            lang = result.get("language", "?")

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


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    global CHUNK_SECONDS, SILENCE_RMS_THRESHOLD

    parser = argparse.ArgumentParser(description="Live dual-channel Whisper transcription")
    parser.add_argument("--list-devices", action="store_true", help="Print audio devices and exit")
    parser.add_argument("--me", type=int, default=None, metavar="IDX", help="Device index for 'me' channel")
    parser.add_argument("--audience", type=int, default=None, metavar="IDX", help="Device index for 'audience' channel")
    parser.add_argument("--no-audience", action="store_true", help="Skip audience channel")
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

    me_idx = args.me
    if me_idx is None:
        me_idx = pick_device("  Device index for [me] (your mic): ")

    audience_idx = args.audience
    if not args.no_audience and audience_idx is None:
        print("  For Loopback app: look for 'Loopback Audio' or your virtual device above.")
        audience_idx = pick_device("  Device index for [audience] (Loopback virtual device, or 'n' to skip): ")

    channels: list[ChannelCapture] = []
    tx_queue: queue.Queue = queue.Queue()

    if me_idx is not None:
        channels.append(ChannelCapture(me_idx, "me", tx_queue))
    if audience_idx is not None:
        channels.append(ChannelCapture(audience_idx, "audience", tx_queue))

    if not channels:
        print("No channels configured. Exiting.")
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
