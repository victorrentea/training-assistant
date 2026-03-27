from pathlib import Path

from daemon.rag import indexer


def _write_manifest(folder: Path, files: dict[str, str]):
    indexer._save_manifest(folder, files)


def test_index_all_skips_unchanged_files(tmp_path: Path, monkeypatch):
    f = tmp_path / "a.txt"
    f.write_text("same", encoding="utf-8")
    file_hash = indexer._hash_file(f)
    _write_manifest(tmp_path, {"a.txt": file_hash})

    indexed: list[str] = []
    removed: list[str] = []

    monkeypatch.setattr(indexer, "index_file", lambda p, base: indexed.append(str(p.relative_to(base))) or True)
    monkeypatch.setattr(indexer, "deindex_file", lambda source: removed.append(source))

    indexer.index_all(tmp_path)

    assert indexed == []
    assert removed == []
    assert indexer._load_manifest(tmp_path) == {"a.txt": file_hash}


def test_index_all_reindexes_changed_adds_new_and_removes_deleted(tmp_path: Path, monkeypatch):
    a = tmp_path / "a.txt"
    c = tmp_path / "c.md"
    a.write_text("new-a", encoding="utf-8")
    c.write_text("new-c", encoding="utf-8")

    old_a_hash = "old-a-hash"
    old_b_hash = "old-b-hash"
    _write_manifest(tmp_path, {"a.txt": old_a_hash, "b.txt": old_b_hash})

    indexed: list[str] = []
    removed: list[str] = []

    monkeypatch.setattr(indexer, "index_file", lambda p, base: indexed.append(str(p.relative_to(base))) or True)
    monkeypatch.setattr(indexer, "deindex_file", lambda source: removed.append(source))

    indexer.index_all(tmp_path)

    # Changed file a.txt is deindexed then reindexed; missing b.txt is deindexed; new c.md is indexed.
    assert "a.txt" in removed
    assert "b.txt" in removed
    assert set(indexed) == {"a.txt", "c.md"}

    manifest = indexer._load_manifest(tmp_path)
    assert set(manifest.keys()) == {"a.txt", "c.md"}
    assert manifest["a.txt"] == indexer._hash_file(a)
    assert manifest["c.md"] == indexer._hash_file(c)

