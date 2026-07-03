"""Unit tests for the per-participant overlay glow colour."""
import re

from daemon.emoji.glow import color_for_participant

HEX = re.compile(r"^#[0-9a-f]{6}$")


def test_returns_valid_hex():
    assert HEX.match(color_for_participant("uuid-abc"))


def test_deterministic_and_stable():
    # Same id → same colour, every time (must survive daemon restarts).
    assert color_for_participant("uuid-abc") == color_for_participant("uuid-abc")


def test_distinct_ids_get_distinct_colours():
    # Not a guarantee for every pair, but a handful of ids should not all collide.
    colours = {color_for_participant(f"uuid-{i}") for i in range(20)}
    assert len(colours) >= 18


def test_host_gets_a_colour_like_anyone_else():
    # No special-casing: __host__ hashes to a stable colour too.
    assert HEX.match(color_for_participant("__host__"))
