"""Tests for /internal/upload-static and /internal/delete-static."""
import base64
import pytest
from conftest import api


class TestUploadStatic:
    def test_upload_creates_file(self, server_url):
        content = b"console.log('test');"
        resp = api(server_url, "post", "/internal/upload-static", json={
            "path": "test-upload.js",
            "content_b64": base64.b64encode(content).decode(),
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["size"] == len(content)

    def test_upload_subdirectory_file(self, server_url):
        content = b"/* avatar css */"
        resp = api(server_url, "post", "/internal/upload-static", json={
            "path": "avatars/test-avatar.css",
            "content_b64": base64.b64encode(content).decode(),
        })
        assert resp.status_code == 200

    def test_upload_rejects_path_traversal(self, server_url):
        resp = api(server_url, "post", "/internal/upload-static", json={
            "path": "../main.py",
            "content_b64": base64.b64encode(b"evil").decode(),
        })
        assert resp.status_code == 400

    def test_upload_rejects_excluded_files(self, server_url):
        for name in ["version.js", "deploy-info.json", "work-hours.js"]:
            resp = api(server_url, "post", "/internal/upload-static", json={
                "path": name,
                "content_b64": base64.b64encode(b"fake").decode(),
            })
            assert resp.status_code == 400, f"Expected 400 for {name}"

    def test_upload_rejects_disallowed_extension(self, server_url):
        resp = api(server_url, "post", "/internal/upload-static", json={
            "path": "malware.exe",
            "content_b64": base64.b64encode(b"bad").decode(),
        })
        assert resp.status_code == 400

    def test_upload_requires_auth(self, server_url):
        import requests
        resp = requests.post(f"{server_url}/internal/upload-static", json={
            "path": "test.js",
            "content_b64": base64.b64encode(b"x").decode(),
        })
        assert resp.status_code == 401


class TestDeleteStatic:
    def test_delete_nonexistent_returns_ok(self, server_url):
        resp = api(server_url, "post", "/internal/delete-static", json={
            "path": "does-not-exist.js",
        })
        assert resp.status_code == 200
        assert resp.json()["action"] == "not_found"

    def test_delete_rejects_path_traversal(self, server_url):
        resp = api(server_url, "post", "/internal/delete-static", json={
            "path": "../main.py",
        })
        assert resp.status_code == 400
