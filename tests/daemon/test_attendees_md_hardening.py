"""Hardening tests for attendees.md: Markdown injection defense (fix #3) and the
explicit anonymity signal (fix #4)."""

from daemon import attendees_md


def _p(name, uuid=None):
    entry = {"name": name}
    if uuid is not None:
        entry["uuid"] = uuid
    return entry


# ── Fix #3: Markdown metacharacter escaping at the sink ───────────────────────

class TestMarkdownInjectionDefense:
    def test_link_injection_escaped(self, tmp_path):
        folder = tmp_path / "2026-07-24 Session"
        folder.mkdir()
        out = attendees_md.render_attendees_md(folder, [_p("[click](http://evil.example)")], None)
        # The raw link syntax must not survive unescaped.
        assert "[click](http://evil.example)" not in out
        assert "\\[click\\]\\(http://evil.example\\)" in out

    def test_heading_and_rule_chars_neutralized(self, tmp_path):
        folder = tmp_path / "2026-07-24 Session"
        folder.mkdir()
        out = attendees_md.render_attendees_md(folder, [_p("**bold** _em_ `code`")], None)
        assert "**bold**" not in out
        assert "\\*\\*bold\\*\\* \\_em\\_ \\`code\\`" in out

    def test_html_injection_escaped(self, tmp_path):
        folder = tmp_path / "2026-07-24 Session"
        folder.mkdir()
        out = attendees_md.render_attendees_md(folder, [_p("<img src=x onerror=alert(1)>")], None)
        # The `<` and `>` are escaped so markdown won't pass the tag through as
        # raw HTML — every angle bracket is backslash-escaped.
        assert "\\<img src=x onerror=alert\\(1\\)\\>" in out
        # No UNescaped tag opener survives.
        assert out.replace("\\<", "").find("<") == -1

    def test_no_extra_rows_injected_via_name(self, tmp_path):
        folder = tmp_path / "2026-07-24 Session"
        folder.mkdir()
        # Even if a newline slipped past ingest, the sink must not split it into
        # extra numbered rows.
        out = attendees_md.render_attendees_md(folder, [_p("Ada\n99. Injected")], None)
        numbered = [ln for ln in out.splitlines() if ln[:1].isdigit()]
        assert len(numbered) == 1  # only the single real attendee row
        # The newline is folded to a space, keeping the injected text on the same
        # line as Ada rather than becoming its own numbered row.
        assert "1. Ada 99. Injected" in out

    def test_table_pipe_escaped(self, tmp_path):
        folder = tmp_path / "2026-07-24 Session"
        folder.mkdir()
        out = attendees_md.render_attendees_md(folder, [_p("a|b|c")], None)
        assert "\\|" in out

    def test_header_from_folder_is_escaped(self, tmp_path):
        folder = tmp_path / "2026-07-24 [x](y) Session"
        folder.mkdir()
        out = attendees_md.render_attendees_md(folder, [_p("Ada")], None)
        header = next(ln for ln in out.splitlines() if ln.startswith("# Attendance"))
        assert "[x](y)" not in header
        assert "\\[x\\]\\(y\\)" in header

    def test_normal_names_and_dates_unmangled(self, tmp_path):
        # `-` and `.` are intentionally preserved so real names/dates read cleanly.
        folder = tmp_path / "2026-07-24 AcmeCorp Session"
        folder.mkdir()
        out = attendees_md.render_attendees_md(
            folder, [_p("Anne-Marie J.R.R"), _p("Ada Lovelace")], None
        )
        assert "# Attendance — 2026-07-24 AcmeCorp Session" in out
        assert "Anne-Marie J.R.R" in out
        assert "Ada Lovelace" in out


# ── Fix #4: explicit anonymity signal supersedes the name heuristic ───────────

class TestExplicitAnonymitySignal:
    def test_typed_pool_name_not_anonymous(self, tmp_path):
        """A participant who typed "Frodo" (uuid absent from the signal set) is
        rendered as a real name, NOT "(anonymous)"."""
        folder = tmp_path / "2026-07-24 Session"
        folder.mkdir()
        out = attendees_md.render_attendees_md(
            folder,
            [_p("Frodo", uuid="u1")],
            None,
            anonymous_pids=set(),  # u1 typed the name → not anonymous
        )
        assert "(anonymous)" not in out
        frodo_line = next(ln for ln in out.splitlines() if "Frodo" in ln)
        assert "(anonymous)" not in frodo_line

    def test_signalled_pid_is_anonymous_even_with_realish_name(self, tmp_path):
        folder = tmp_path / "2026-07-24 Session"
        folder.mkdir()
        out = attendees_md.render_attendees_md(
            folder,
            [_p("Gandalf", uuid="u1")],
            None,
            anonymous_pids={"u1"},  # auto-assigned → anonymous
        )
        assert "_Gandalf_ (anonymous)" in out
        assert "(1 anonymous)" in out

    def test_no_uuid_falls_back_to_name_heuristic(self, tmp_path):
        """Entries without a uuid (legacy/direct render) keep the old name-only
        heuristic so nothing regresses."""
        folder = tmp_path / "2026-07-24 Session"
        folder.mkdir()
        out = attendees_md.render_attendees_md(folder, [_p("Gandalf")], None)  # no uuid, no signal
        assert "_Gandalf_ (anonymous)" in out

    def test_regenerate_uses_state_signal(self, tmp_path):
        """End-to-end: regenerate_attendees reads participant_state.anonymous_pids."""
        from daemon.participant.state import participant_state as ps
        from daemon.scores import scores

        ps.reset(mode="workshop")
        scores.scores.clear()
        try:
            # u1 typed "Frodo" (real); u2 auto-assigned "Gandalf" (anonymous).
            ps.participant_names.update({"u1": "Frodo", "u2": "Gandalf"})
            ps.anonymous_pids.add("u2")
            folder = tmp_path / "2026-07-24 Session"
            folder.mkdir()
            text = attendees_md.regenerate_attendees(folder=folder).read_text()
            # Frodo is a real, typed name → NOT tagged.
            frodo_line = next(ln for ln in text.splitlines() if "Frodo" in ln)
            assert "(anonymous)" not in frodo_line
            # Gandalf carries the explicit signal → tagged.
            assert "_Gandalf_ (anonymous)" in text
            assert "(1 anonymous)" in text
        finally:
            ps.reset(mode="workshop")
            scores.scores.clear()
