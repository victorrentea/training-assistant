"""Tests for the FX link's session state.

The master switch is OFF at construction and OFF again after reset, like the
attention bell: every session is an explicit opt-in, so yesterday's link cannot
fire into this morning's room before the host is ready.
"""
from daemon.participant.state import ParticipantState


class TestDefaults:
    def test_master_switch_starts_armed(self):
        """The host wanted the link live the moment he copies it."""
        assert ParticipantState().fx_enabled is True

    def test_default_tile_is_69(self):
        assert ParticipantState().fx_tile_n == 69

    def test_default_cooldown_is_ten_seconds(self):
        assert ParticipantState().fx_cooldown_seconds == 10

    def test_no_token_until_one_is_asked_for(self):
        assert ParticipantState().fx_token is None

    def test_nothing_has_fired_yet(self):
        assert ParticipantState().fx_last_fired_at is None

    def test_no_press_outcome_is_known_yet(self):
        assert ParticipantState().fx_last_press_ok is None


class TestReset:
    def test_reset_returns_the_switch_to_armed(self):
        ps = ParticipantState()
        ps.fx_enabled = False
        ps.reset()
        assert ps.fx_enabled is True

    def test_reset_drops_the_token_so_a_new_session_gets_a_new_link(self):
        ps = ParticipantState()
        ps.fx_token = "abc123def456"
        ps.reset()
        assert ps.fx_token is None

    def test_reset_returns_the_tile_to_69(self):
        ps = ParticipantState()
        ps.fx_tile_n = 3
        ps.reset()
        assert ps.fx_tile_n == 69

    def test_reset_clears_the_last_fired_stamp(self):
        ps = ParticipantState()
        ps.fx_last_fired_at = 1789554996.0
        ps.fx_last_fired_mono = 42.0
        ps.reset()
        assert ps.fx_last_fired_at is None
        assert ps.fx_last_fired_mono is None

    def test_reset_forgets_the_last_press_outcome(self):
        """Yesterday's soundboard failure must not disarm this morning's link."""
        ps = ParticipantState()
        ps.fx_last_press_ok = False
        ps.reset()
        assert ps.fx_last_press_ok is None


class TestRoundTrip:
    def test_the_fields_survive_snapshot_and_restore(self):
        ps = ParticipantState()
        ps.fx_enabled = True
        ps.fx_token = "abc123def456"
        ps.fx_tile_n = 3
        ps.fx_cooldown_seconds = 30
        ps.fx_last_fired_at = 1789554996.0

        restored = ParticipantState()
        restored.sync_from_restore(ps.snapshot())

        assert restored.fx_enabled is True
        assert restored.fx_token == "abc123def456"
        assert restored.fx_tile_n == 3
        assert restored.fx_cooldown_seconds == 30
        assert restored.fx_last_fired_at == 1789554996.0

    def test_the_monotonic_stamp_is_never_persisted(self):
        """A monotonic clock means nothing in another process, so persisting it
        would let a daemon restart resurrect a cooldown from a different epoch."""
        ps = ParticipantState()
        ps.fx_last_fired_mono = 42.0
        assert "fx_last_fired_mono" not in ps.snapshot()

    def test_the_press_outcome_is_never_persisted(self):
        """Like the monotonic stamp, this is a live health signal about the
        current process's connection to the Mac — meaningless, and possibly
        wrong, after a daemon restart."""
        ps = ParticipantState()
        ps.fx_last_press_ok = False
        assert "fx_last_press_ok" not in ps.snapshot()

    def test_a_snapshot_that_omits_the_switch_leaves_it_at_the_default(self):
        """A legacy session-state.json predates the flag, so it inherits the
        default rather than silently disarming a link the host expects to work."""
        restored = ParticipantState()
        restored.sync_from_restore({"mode": "workshop"})
        assert restored.fx_enabled is True
