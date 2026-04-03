"""Tests for daemon static file sync logic."""
import hashlib
from pathlib import Path

from daemon.static_sync import compute_local_hashes, diff_hashes, sync_static_files


class TestComputeLocalHashes:
    def test_hashes_files(self, tmp_path):
        (tmp_path / "a.js").write_text("console.log('a');")
        (tmp_path / "b.css").write_text("body { color: red; }")
        hashes = compute_local_hashes(tmp_path)
        assert "a.js" in hashes
        assert "b.css" in hashes
        assert hashes["a.js"] == hashlib.md5(b"console.log('a');").hexdigest()

    def test_excludes_version_js(self, tmp_path):
        (tmp_path / "version.js").write_text("window.APP_VERSION='test';")
        (tmp_path / "app.js").write_text("ok")
        hashes = compute_local_hashes(tmp_path)
        assert "version.js" not in hashes
        assert "app.js" in hashes

    def test_excludes_deploy_info(self, tmp_path):
        (tmp_path / "deploy-info.json").write_text("{}")
        hashes = compute_local_hashes(tmp_path)
        assert "deploy-info.json" not in hashes

    def test_excludes_work_hours(self, tmp_path):
        (tmp_path / "work-hours.js").write_text("const h=1;")
        hashes = compute_local_hashes(tmp_path)
        assert "work-hours.js" not in hashes

    def test_recursive_scan(self, tmp_path):
        sub = tmp_path / "avatars"
        sub.mkdir()
        (sub / "gandalf.png").write_bytes(b"png data")
        (tmp_path / "app.js").write_text("ok")
        hashes = compute_local_hashes(tmp_path)
        assert "avatars/gandalf.png" in hashes
        assert "app.js" in hashes

    def test_empty_dir(self, tmp_path):
        assert compute_local_hashes(tmp_path) == {}

    def test_nonexistent_dir(self, tmp_path):
        assert compute_local_hashes(tmp_path / "nope") == {}


class TestDiffHashes:
    def test_new_file(self):
        to_upload, to_delete = diff_hashes({"a.js": "abc"}, {})
        assert to_upload == ["a.js"]
        assert to_delete == []

    def test_changed_file(self):
        to_upload, to_delete = diff_hashes({"a.js": "new"}, {"a.js": "old"})
        assert to_upload == ["a.js"]
        assert to_delete == []

    def test_deleted_file(self):
        to_upload, to_delete = diff_hashes({}, {"a.js": "abc"})
        assert to_upload == []
        assert to_delete == ["a.js"]

    def test_no_changes(self):
        to_upload, to_delete = diff_hashes({"a.js": "abc"}, {"a.js": "abc"})
        assert to_upload == []
        assert to_delete == []

    def test_mixed(self):
        local = {"a.js": "new_a", "c.js": "c_hash"}
        remote = {"a.js": "old_a", "b.js": "b_hash"}
        to_upload, to_delete = diff_hashes(local, remote)
        assert set(to_upload) == {"a.js", "c.js"}
        assert to_delete == ["b.js"]
