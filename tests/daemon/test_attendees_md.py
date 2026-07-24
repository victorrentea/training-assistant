"""Tests for the live `attendees.md` attendance sheet (session-attendees-file)."""



from daemon import attendees_md


def _p(name):
    return {"name": name}


class TestRender:
    def test_header_from_folder_name_and_date(self, tmp_path):
        folder = tmp_path / "2026-07-24 AcmeCorp Clean Architecture"
        folder.mkdir()
        out = attendees_md.render_attendees_md(folder, [_p("Ada Lovelace")], None)
        assert "# Attendance — 2026-07-24 AcmeCorp Clean Architecture" in out
        assert "_Date: 2026-07-24_" in out
        assert "Ada Lovelace" in out

    def test_date_range_folder(self, tmp_path):
        folder = tmp_path / "2026-07-24..25 AcmeCorp Workshop"
        folder.mkdir()
        out = attendees_md.render_attendees_md(folder, [_p("Bob")], None)
        assert "2026-07-24 .. 25" in out

    def test_gdrive_url_in_header(self, tmp_path):
        folder = tmp_path / "2026-07-24 Session"
        folder.mkdir()
        out = attendees_md.render_attendees_md(
            folder, [_p("Bob")], "https://drive.google.com/xyz"
        )
        assert "https://drive.google.com/xyz" in out

    def test_anonymous_entries_are_distinguishable(self, tmp_path):
        folder = tmp_path / "2026-07-24 Session"
        folder.mkdir()
        # 'Gandalf' is an auto-assigned fictional name; 'Ada' is a real name.
        out = attendees_md.render_attendees_md(folder, [_p("Ada"), _p("Gandalf")], None)
        # The anonymous entry carries the explicit tag; the real one is plain.
        assert "_Gandalf_ (anonymous)" in out
        ada_line = next(ln for ln in out.splitlines() if "Ada" in ln)
        assert "(anonymous)" not in ada_line
        # Count summary reflects one anonymous.
        assert "(1 anonymous)" in out

    def test_empty_roster(self, tmp_path):
        folder = tmp_path / "2026-07-24 Session"
        folder.mkdir()
        out = attendees_md.render_attendees_md(folder, [], None)
        assert "No attendees yet" in out

    def test_pool_exhaustion_fallback_names_are_anonymous(self, tmp_path):
        # Guest-<hex> / Hero-<id> are auto-generated when the fictional pools run
        # out — they must not render as confirmed real names.
        folder = tmp_path / "2026-07-24 Session"
        folder.mkdir()
        out = attendees_md.render_attendees_md(
            folder, [_p("Ada"), _p("Guest-a1b2c3"), _p("Hero-x9")], None
        )
        assert "_Guest-a1b2c3_ (anonymous)" in out
        assert "_Hero-x9_ (anonymous)" in out
        assert "(2 anonymous)" in out

    def test_blank_names_excluded(self, tmp_path):
        folder = tmp_path / "2026-07-24 Session"
        folder.mkdir()
        out = attendees_md.render_attendees_md(folder, [_p("Ada"), _p(""), _p("   ")], None)
        assert "**1** attendee" in out


class TestLifecycle:
    # Session (re)init goes through regenerate_attendees() with the (reset or
    # restored) live roster — same path daemon/__main__.py uses.

    def test_regenerate_with_empty_roster_creates_clean_file(self, tmp_path):
        from daemon.participant.state import participant_state as ps

        ps.reset(mode="workshop")
        try:
            folder = tmp_path / "2026-07-24 Session"
            folder.mkdir()
            target = attendees_md.regenerate_attendees(folder=folder)
            assert target == folder / "attendees.md"
            assert target.exists()
            assert "No attendees yet" in target.read_text()
        finally:
            ps.reset(mode="workshop")

    def test_regenerate_clears_stale_content(self, tmp_path):
        from daemon.participant.state import participant_state as ps

        ps.reset(mode="workshop")
        try:
            folder = tmp_path / "2026-07-24 Session"
            folder.mkdir()
            (folder / "attendees.md").write_text("STALE Previous Session Attendee")
            attendees_md.regenerate_attendees(folder=folder)
            assert "STALE" not in (folder / "attendees.md").read_text()
        finally:
            ps.reset(mode="workshop")

    def test_regenerate_reflects_live_roster(self, tmp_path):
        from daemon.participant.state import participant_state as ps
        from daemon.scores import scores

        ps.reset(mode="workshop")
        scores.scores.clear()
        try:
            ps.participant_names.update({"u1": "Ada Lovelace", "u2": "Grace Hopper"})
            folder = tmp_path / "2026-07-24 Session"
            folder.mkdir()
            target = attendees_md.regenerate_attendees(folder=folder)
            text = target.read_text()
            assert "Ada Lovelace" in text
            assert "Grace Hopper" in text
            assert "**2** attendee" in text
        finally:
            ps.reset(mode="workshop")
            scores.scores.clear()

    def test_regenerate_skips_internal_ids(self, tmp_path):
        from daemon.participant.state import participant_state as ps
        from daemon.scores import scores

        ps.reset(mode="workshop")
        scores.scores.clear()
        try:
            ps.participant_names.update({"u1": "Ada", "__host": "HostBot"})
            folder = tmp_path / "2026-07-24 Session"
            folder.mkdir()
            target = attendees_md.regenerate_attendees(folder=folder)
            text = target.read_text()
            assert "Ada" in text
            assert "HostBot" not in text  # __-prefixed ids excluded by enumerator
        finally:
            ps.reset(mode="workshop")
            scores.scores.clear()

    def test_regenerate_no_folder_is_noop(self):
        # No active session folder → returns None, no exception.
        assert attendees_md.regenerate_attendees(folder=None) is None


class TestPersistenceRoundTrip:
    """Real names survive reconnect via participant_state.sync_from_restore, so a
    regenerated attendees.md keeps real names (session-attendees-file requirement)."""

    def test_real_names_round_trip_and_reflect_in_attendees(self, tmp_path):
        from daemon.participant.state import participant_state as ps
        from daemon.scores import scores

        ps.reset(mode="workshop")
        scores.scores.clear()
        try:
            # Simulate a live roster of REAL names, then snapshot it.
            ps.participant_names.update({"u1": "Ada Lovelace", "u2": "Alan Turing"})
            ps.participant_avatars.update({"u1": "letter:AL:#1", "u2": "letter:AT:#2"})
            snap = ps.snapshot()

            # Simulate daemon reconnect/restart: wipe then restore from snapshot.
            ps.reset(mode="workshop")
            assert ps.participant_names == {}
            ps.sync_from_restore(
                {
                    "participant_names": snap["participant_names"],
                    "participant_avatars": snap["participant_avatars"],
                }
            )
            assert ps.participant_names == {"u1": "Ada Lovelace", "u2": "Alan Turing"}

            # Regenerated attendees.md still has the REAL names (not fictional).
            folder = tmp_path / "2026-07-24 Session"
            folder.mkdir()
            text = attendees_md.regenerate_attendees(folder=folder).read_text()
            assert "Ada Lovelace" in text and "Alan Turing" in text
        finally:
            ps.reset(mode="workshop")
            scores.scores.clear()
