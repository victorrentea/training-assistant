"""Stable per-participant glow colour for overlay emoji reactions.

Each participant id maps to a fixed, well-spread colour so the trainer can tell
how many *distinct* people are reacting (five hearts in one colour = one person
insisting; five colours = five people). The emoji itself is unchanged — only a
coloured halo is added downstream.

Anonymous by construction: only a colour is derived here and forwarded to the
local overlay; the participant name/uuid never leaves the daemon.
"""
import colorsys
import hashlib

__all__ = ["color_for_participant"]


def color_for_participant(pid: str) -> str:
    """Deterministic ``#rrggbb`` for a participant id, stable across restarts.

    Uses a stable hash (sha256), not Python's per-process-salted ``hash()``, so
    the same uuid always maps to the same hue even after the daemon restarts.
    Fixed saturation + lightness keep every colour vivid enough for a halo while
    the hue spreads participants around the wheel.
    """
    digest = hashlib.sha256(pid.encode("utf-8")).digest()
    hue = (int.from_bytes(digest[:4], "big") % 360) / 360.0
    r, g, b = colorsys.hls_to_rgb(hue, 0.55, 0.75)  # (hue, lightness, saturation)
    return f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"
