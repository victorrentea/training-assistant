"""Each note's star count mirrored at its foot (`- ⭐ N`), without ever costing a build."""
import io
import os
import unicodedata
import zipfile

from daemon.wiki import builder, downloads
from daemon.wiki.star_lines import strip_star_line, sync_star_lines, with_star_line

NOTE = "# Drift\n\nBody.\n\n---\n- Vezi și: [[Home]]\n"


def test_the_line_is_added_replaced_and_removed_at_the_foot():
    starred = with_star_line(NOTE, 4)
    assert starred == NOTE + "- ⭐ 4\n"
    assert with_star_line(starred, 5) == NOTE + "- ⭐ 5\n"
    assert with_star_line(starred, 0) == NOTE
    assert strip_star_line(NOTE) == NOTE


def test_a_star_in_the_body_is_not_the_star_line():
    text = "# A\n- ⭐ 3 reasons to care\n- more\n"
    assert strip_star_line(text) == text


def test_sync_rewrites_only_the_notes_whose_count_changed(tmp_path):
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "x.md").write_text("# settings\n")
    # macOS may list a name decomposed (e + combining breve); the browser sends it composed.
    nfd = unicodedata.normalize("NFD", "Codul e sursa de adevăr.md")
    (tmp_path / nfd).write_text(NOTE, encoding="utf-8")
    (tmp_path / "Drift.md").write_text(NOTE, encoding="utf-8")
    (tmp_path / "Cold.md").write_text(NOTE, encoding="utf-8")

    assert sync_star_lines(tmp_path, {"Codul-e-sursa-de-adevăr": 2, "Drift": 1}) == 2
    assert (tmp_path / nfd).read_text(encoding="utf-8").endswith("- ⭐ 2\n")
    assert (tmp_path / "Cold.md").read_text(encoding="utf-8") == NOTE
    assert (tmp_path / ".obsidian" / "x.md").read_text() == "# settings\n"

    assert sync_star_lines(tmp_path, {"Codul-e-sursa-de-adevăr": 2}) == 1  # Drift lost its star
    assert (tmp_path / "Drift.md").read_text(encoding="utf-8") == NOTE
    assert sync_star_lines(tmp_path, {"Codul-e-sursa-de-adevăr": 2}) == 0


def test_a_star_line_does_not_change_the_fingerprint(tmp_path):
    page = tmp_path / "Drift.md"
    page.write_text(NOTE, encoding="utf-8")
    os.utime(page, (1000, 1000))
    before = builder.fingerprint(tmp_path)
    sync_star_lines(tmp_path, {"Drift": 3})
    os.utime(page, (2000, 2000))
    assert builder.fingerprint(tmp_path) == before
    page.write_text(NOTE.replace("Body", "New body") + "- ⭐ 3\n", encoding="utf-8")
    os.utime(page, (3000, 3000))
    after = builder.fingerprint(tmp_path)
    assert after.digest != before.digest and after.newest == 3000 * 10**9


def test_the_obsidian_download_carries_the_line_with_the_build_time_count(tmp_path):
    (tmp_path / "Drift.md").write_text(NOTE + "- ⭐ 1\n", encoding="utf-8")
    payload = downloads.vault_zip(tmp_path, "T", {"Drift": 3}, set())
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        text = z.read("T wiki/Drift.md").decode()
    assert text.startswith("---\nstars: 3\n---\n") and text.endswith("- ⭐ 3\n")
