import pytest

from railway.features.drive_relay.exclusions import is_excluded_dir, is_excluded_file


@pytest.mark.parametrize("name", [
    "session-state.json",
    "attendees.md",
    "Icon",
    "Icon\r",
    "~$Slides.pptx",
    "~$notes.docx",
])
def test_internal_files_are_excluded(name):
    assert is_excluded_file(name) is True


@pytest.mark.parametrize("name", [
    "Intro.pdf",
    "ai-summary.md",
    "opened-files.md",
    "Workshop - notes.txt",
    "session-state.json.bak",
    "my-attendees.md",
])
def test_course_materials_are_kept(name):
    assert is_excluded_file(name) is False


def test_zip_files_are_kept():
    """The daemon skips zips so its archive won't nest; the relay has no such problem."""
    assert is_excluded_file("wiki.zip") is False
    assert is_excluded_file("wiki-day1.zip") is False


def test_obsidian_directory_is_excluded():
    assert is_excluded_dir(".obsidian") is True


@pytest.mark.parametrize("name", ["uploads", "wiki", "Day 2", "obsidian"])
def test_content_directories_are_kept(name):
    assert is_excluded_dir(name) is False
