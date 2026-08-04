import pytest

from railway.features.drive_relay import tree
from railway.features.drive_relay.drive_client import FOLDER_MIME, SHORTCUT_MIME, DriveFile


def folder(id, name):
    return DriveFile(id=id, name=name, mime_type=FOLDER_MIME, size=None, owners=(),
                     shortcut_target_id=None)


def pdf(id, name, size=100):
    return DriveFile(id=id, name=name, mime_type="application/pdf", size=size, owners=(),
                     shortcut_target_id=None)


def doc(id, name):
    return DriveFile(id=id, name=name, mime_type="application/vnd.google-apps.document",
                     size=None, owners=(), shortcut_target_id=None)


def shortcut(id, name, target):
    return DriveFile(id=id, name=name, mime_type=SHORTCUT_MIME, size=None, owners=(),
                     shortcut_target_id=target)


@pytest.fixture
def drive(monkeypatch):
    """A fake Drive: {folder_id: [children]} plus {id: file} for shortcut targets."""
    tree_map, by_id = {}, {}
    monkeypatch.setattr(tree.drive_client, "list_children", lambda fid: tree_map.get(fid, []))
    monkeypatch.setattr(tree.drive_client, "get_metadata", lambda fid: by_id[fid])
    return tree_map, by_id


def test_single_file_plan_has_one_entry():
    plan = tree.build_plan(pdf("f1", "Deck.pdf", size=2048))

    assert plan.root_name == "Deck.pdf"
    assert [e.archive_path for e in plan.entries] == ["Deck.pdf"]
    assert plan.known_bytes == 2048
    assert plan.has_unsized_files is False


def test_nested_folders_keep_their_structure(drive):
    tree_map, _ = drive
    tree_map["root"] = [pdf("a", "Intro.pdf"), folder("sub", "Day 2")]
    tree_map["sub"] = [pdf("b", "Lab.pdf"), folder("deep", "Solutions")]
    tree_map["deep"] = [pdf("c", "Answer.pdf")]

    plan = tree.build_plan(folder("root", "Workshop"))

    assert [e.archive_path for e in plan.entries] == [
        "Intro.pdf", "Day 2/Lab.pdf", "Day 2/Solutions/Answer.pdf",
    ]
    assert plan.known_bytes == 300


def test_empty_folders_produce_no_entries(drive):
    tree_map, _ = drive
    tree_map["root"] = [folder("empty", "Nothing")]
    tree_map["empty"] = []

    assert tree.build_plan(folder("root", "Workshop")).entries == ()


def test_native_files_are_planned_as_pdf_and_flagged_unsized(drive):
    tree_map, _ = drive
    tree_map["root"] = [doc("d1", "Agenda")]

    plan = tree.build_plan(folder("root", "Workshop"))

    assert [e.archive_path for e in plan.entries] == ["Agenda.pdf"]
    assert plan.known_bytes == 0
    assert plan.has_unsized_files is True


def test_shortcuts_are_resolved_to_their_target(drive):
    tree_map, by_id = drive
    tree_map["root"] = [shortcut("s1", "Link to deck", "t1")]
    by_id["t1"] = pdf("t1", "RealDeck.pdf", size=500)

    plan = tree.build_plan(folder("root", "Workshop"))

    assert [e.archive_path for e in plan.entries] == ["RealDeck.pdf"]
    assert plan.known_bytes == 500


def test_duplicate_names_in_one_folder_are_disambiguated(drive):
    tree_map, _ = drive
    tree_map["root"] = [pdf("a", "Notes.pdf"), pdf("b", "Notes.pdf"), pdf("c", "Notes.pdf")]

    paths = [e.archive_path for e in tree.build_plan(folder("root", "W")).entries]

    assert paths == ["Notes.pdf", "Notes (2).pdf", "Notes (3).pdf"]


def test_same_name_in_different_folders_is_left_alone(drive):
    tree_map, _ = drive
    tree_map["root"] = [pdf("a", "Notes.pdf"), folder("sub", "Day 2")]
    tree_map["sub"] = [pdf("b", "Notes.pdf")]

    paths = [e.archive_path for e in tree.build_plan(folder("root", "W")).entries]

    assert paths == ["Notes.pdf", "Day 2/Notes.pdf"]


def test_path_separators_in_drive_names_cannot_escape_the_archive(drive):
    tree_map, _ = drive
    tree_map["root"] = [pdf("a", "../../etc/passwd"), pdf("b", "a/b.pdf")]

    paths = [e.archive_path for e in tree.build_plan(folder("root", "W")).entries]

    # NOTE: deviates from the task-5 brief's literal ["......etc.passwd", "a.b.pdf"].
    # That expectation is self-contradicting: a run of 6 dots still contains ".."
    # as a substring, so it cannot satisfy the very safety assertion below in the
    # same test. Separators are flattened to ".", and any run of 2+ dots left
    # over from the original name (e.g. from "..") is then collapsed to a single
    # "." so no ".." substring can ever survive into an archive path.
    assert paths == [".etc.passwd", "a.b.pdf"]
    assert not any(p.startswith("/") or ".." in p for p in paths)


def test_internal_session_files_are_dropped(drive):
    """A real session folder on Drive carries these; participants must not get them."""
    tree_map, _ = drive
    tree_map["root"] = [
        pdf("a", "ai-summary.md", 10),
        pdf("b", "attendees.md", 20),
        pdf("c", "session-state.json", 30),
        pdf("d", "wiki.zip", 40),
    ]

    plan = tree.build_plan(folder("root", "Workshop"))

    assert [e.archive_path for e in plan.entries] == ["ai-summary.md", "wiki.zip"]
    assert plan.known_bytes == 50  # excluded files must not count toward the cap


def test_excluded_directories_are_not_descended_into(drive):
    tree_map, _ = drive
    tree_map["root"] = [folder("obs", ".obsidian"), pdf("a", "Intro.pdf", 10)]
    tree_map["obs"] = [pdf("x", "workspace.json", 5)]

    plan = tree.build_plan(folder("root", "Workshop"))

    assert [e.archive_path for e in plan.entries] == ["Intro.pdf"]


def test_a_folder_cycle_terminates(drive):
    tree_map, _ = drive
    tree_map["root"] = [folder("loop", "Loop")]
    tree_map["loop"] = [folder("root", "Back"), pdf("a", "Real.pdf")]

    plan = tree.build_plan(folder("root", "Workshop"))

    assert [e.archive_path for e in plan.entries] == ["Loop/Real.pdf"]


def test_depth_is_bounded(drive):
    tree_map, _ = drive
    for depth in range(tree.MAX_DEPTH + 5):
        tree_map[f"f{depth}"] = [folder(f"f{depth + 1}", f"L{depth + 1}")]
    tree_map[f"f{tree.MAX_DEPTH + 5}"] = [pdf("deep", "TooDeep.pdf")]

    plan = tree.build_plan(folder("f0", "Root"))

    assert plan.entries == ()
