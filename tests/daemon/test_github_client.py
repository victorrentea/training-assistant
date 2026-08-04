from unittest.mock import patch

import pytest

from daemon import github_client


@pytest.fixture(autouse=True)
def reset_cache():
    github_client.reset_cache()
    yield
    github_client.reset_cache()


def _fake_resp(status: int, body: bytes = b"{}", headers: dict | None = None):
    class _Resp:
        def __init__(self):
            self.status = status
            self._body = body
            self.headers = headers or {}

        def read(self):
            return self._body

        def getcode(self):
            return self.status

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return _Resp()


def test_get_repo_info_public_returns_default_branch():
    body = b'{"default_branch":"main"}'
    with patch("urllib.request.urlopen", return_value=_fake_resp(200, body)):
        info = github_client.get_repo_info("owner", "repo")
    assert info is not None
    assert info.default_branch == "main"


def test_get_repo_info_404_returns_none():
    import urllib.error
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError("u", 404, "Not Found", {}, None),
    ):
        info = github_client.get_repo_info("owner", "missing")
    assert info is None


def test_get_repo_info_403_returns_none():
    import urllib.error
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError("u", 403, "Forbidden", {}, None),
    ):
        info = github_client.get_repo_info("owner", "private")
    assert info is None


def test_get_repo_info_is_cached_after_success():
    body = b'{"default_branch":"main"}'
    with patch("urllib.request.urlopen", return_value=_fake_resp(200, body)) as mock:
        github_client.get_repo_info("owner", "repo")
        github_client.get_repo_info("owner", "repo")
        github_client.get_repo_info("owner", "repo")
    assert mock.call_count == 1


def test_get_repo_info_caches_negative_lookup():
    import urllib.error
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError("u", 404, "x", {}, None),
    ) as mock:
        github_client.get_repo_info("owner", "missing")
        github_client.get_repo_info("owner", "missing")
    assert mock.call_count == 1


def test_get_repo_info_returns_rate_limited_sentinel():
    import urllib.error
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(
            "u", 403, "rate limited",
            {"X-RateLimit-Remaining": "0"},
            None,
        ),
    ):
        info = github_client.get_repo_info("owner", "repo")
    assert info is github_client.RATE_LIMITED


def test_get_repo_info_does_not_cache_rate_limited():
    import urllib.error
    err = urllib.error.HTTPError(
        "u", 403, "rate limited", {"X-RateLimit-Remaining": "0"}, None,
    )
    with patch("urllib.request.urlopen", side_effect=err) as mock:
        github_client.get_repo_info("owner", "repo")
        github_client.get_repo_info("owner", "repo")
    assert mock.call_count == 2


def test_head_blob_200_returns_true():
    with patch("urllib.request.urlopen", return_value=_fake_resp(200)):
        assert github_client.head_blob("owner", "repo", "main", "src/a.py") is True


def test_head_blob_404_returns_false():
    import urllib.error
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError("u", 404, "x", {}, None),
    ):
        assert github_client.head_blob("owner", "repo", "main", "src/missing.py") is False


def test_head_blob_uses_HEAD_method():
    captured = {}

    def fake_urlopen(req, **kw):
        captured["method"] = req.get_method()
        return _fake_resp(200)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        github_client.head_blob("owner", "repo", "main", "src/a.py")
    assert captured["method"] == "HEAD"


def test_get_repo_info_does_not_cache_network_errors():
    import urllib.error
    err = urllib.error.URLError("network down")
    with patch("urllib.request.urlopen", side_effect=err) as mock:
        result1 = github_client.get_repo_info("owner", "repo")
        result2 = github_client.get_repo_info("owner", "repo")
    assert result1 is None
    assert result2 is None
    assert mock.call_count == 2  # NOT cached — retried


def test_get_repo_info_does_not_cache_500_error():
    import urllib.error
    err = urllib.error.HTTPError("u", 500, "Internal", {}, None)
    with patch("urllib.request.urlopen", side_effect=err) as mock:
        result1 = github_client.get_repo_info("owner", "repo")
        result2 = github_client.get_repo_info("owner", "repo")
    assert result1 is None
    assert result2 is None
    assert mock.call_count == 2  # NOT cached — transient, retried


# ---------------------------------------------------------------------------
# get_repo_tree tests
# ---------------------------------------------------------------------------

def test_get_repo_tree_lists_blob_paths_only():
    import json
    body = json.dumps({
        "tree": [
            {"type": "blob", "path": "docs/packages.puml"},
            {"type": "blob", "path": "src/a.py"},
            {"type": "tree", "path": "src"},  # dir, should be skipped
        ],
        "truncated": False,
    }).encode("utf-8")
    with patch("urllib.request.urlopen", return_value=_fake_resp(200, body)):
        tree = github_client.get_repo_tree("owner", "repo", "main")
    assert tree is not None
    assert tree.truncated is False
    assert "docs/packages.puml" in tree.paths
    assert "src/a.py" in tree.paths
    assert "src" not in tree.paths  # directories excluded


def test_get_repo_tree_truncated_flag_propagated():
    import json
    body = json.dumps({
        "tree": [{"type": "blob", "path": "x.py"}],
        "truncated": True,
    }).encode("utf-8")
    with patch("urllib.request.urlopen", return_value=_fake_resp(200, body)):
        tree = github_client.get_repo_tree("owner", "repo", "main")
    assert tree is not None
    assert tree.truncated is True


def test_get_repo_tree_404_returns_none_and_is_cached():
    import urllib.error
    err = urllib.error.HTTPError("u", 404, "Not Found", {}, None)
    with patch("urllib.request.urlopen", side_effect=err) as mock:
        result1 = github_client.get_repo_tree("owner", "missing", "main")
        result2 = github_client.get_repo_tree("owner", "missing", "main")
    assert result1 is None
    assert result2 is None
    assert mock.call_count == 1  # cached after first call


def test_get_repo_tree_rate_limited_returns_unknown_and_not_cached():
    import urllib.error
    err = urllib.error.HTTPError(
        "u", 403, "rate limited", {"X-RateLimit-Remaining": "0"}, None,
    )
    with patch("urllib.request.urlopen", side_effect=err) as mock:
        result1 = github_client.get_repo_tree("owner", "repo", "main")
        result2 = github_client.get_repo_tree("owner", "repo", "main")
    # UNKNOWN, not None: a rate limit says nothing about whether the ref
    # exists, so it must never be conflated with a definitive 404/403.
    assert result1 is github_client.UNKNOWN
    assert result2 is github_client.UNKNOWN
    assert mock.call_count == 2  # NOT cached — retried both times


def test_get_repo_tree_500_returns_unknown_and_not_cached():
    import urllib.error
    err = urllib.error.HTTPError("u", 500, "Internal", {}, None)
    with patch("urllib.request.urlopen", side_effect=err) as mock:
        result1 = github_client.get_repo_tree("owner", "repo", "main")
        result2 = github_client.get_repo_tree("owner", "repo", "main")
    assert result1 is github_client.UNKNOWN
    assert result2 is github_client.UNKNOWN
    assert mock.call_count == 2  # NOT cached — a 5xx is transient


def test_get_repo_tree_network_error_returns_unknown_and_not_cached():
    import urllib.error
    err = urllib.error.URLError("network down")
    with patch("urllib.request.urlopen", side_effect=err) as mock:
        result1 = github_client.get_repo_tree("owner", "repo", "main")
        result2 = github_client.get_repo_tree("owner", "repo", "main")
    assert result1 is github_client.UNKNOWN
    assert result2 is github_client.UNKNOWN
    assert mock.call_count == 2  # NOT cached — transient


def test_get_repo_tree_is_cached_after_success():
    import json
    body = json.dumps({"tree": [{"type": "blob", "path": "x.py"}], "truncated": False}).encode()
    with patch("urllib.request.urlopen", return_value=_fake_resp(200, body)) as mock:
        github_client.get_repo_tree("owner", "repo", "main")
        github_client.get_repo_tree("owner", "repo", "main")
    assert mock.call_count == 1


def test_head_blob_500_returns_unknown():
    import urllib.error
    err = urllib.error.HTTPError("u", 500, "Internal", {}, None)
    with patch("urllib.request.urlopen", side_effect=err):
        assert github_client.head_blob("owner", "repo", "main", "src/a.py") is github_client.UNKNOWN


def test_head_blob_network_error_returns_unknown():
    import urllib.error
    err = urllib.error.URLError("network down")
    with patch("urllib.request.urlopen", side_effect=err):
        assert github_client.head_blob("owner", "repo", "main", "src/a.py") is github_client.UNKNOWN


def test_head_blob_rate_limited_returns_unknown():
    import urllib.error
    err = urllib.error.HTTPError(
        "u", 403, "rate limited", {"X-RateLimit-Remaining": "0"}, None,
    )
    with patch("urllib.request.urlopen", side_effect=err):
        assert github_client.head_blob("owner", "repo", "main", "src/a.py") is github_client.UNKNOWN


def test_head_blob_percent_encodes_the_path():
    captured = {}

    def fake_urlopen(req, **kw):
        captured["url"] = req.full_url
        return _fake_resp(200)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        github_client.head_blob("owner", "repo", "main", "src/my folder/a.py")
    assert captured["url"] == "https://github.com/owner/repo/blob/main/src/my%20folder/a.py"


# ---------------------------------------------------------------------------
# build_blob_url tests
# ---------------------------------------------------------------------------

def test_build_blob_url_percent_encodes_spaces():
    assert github_client.build_blob_url("owner", "repo", "main", "src/my folder/a.py") == (
        "https://github.com/owner/repo/blob/main/src/my%20folder/a.py"
    )


def test_build_blob_url_percent_encodes_parens():
    assert github_client.build_blob_url("owner", "repo", "main", "src/a(1).java") == (
        "https://github.com/owner/repo/blob/main/src/a%281%29.java"
    )


def test_build_blob_url_keeps_slashes_unescaped():
    assert github_client.build_blob_url("owner", "repo", "main", "src/a/b.java") == (
        "https://github.com/owner/repo/blob/main/src/a/b.java"
    )


def test_get_repo_tree_skips_directory_entries():
    import json
    body = json.dumps({
        "tree": [
            {"type": "tree", "path": "src"},
            {"type": "tree", "path": "docs"},
            {"type": "blob", "path": "README.md"},
        ],
        "truncated": False,
    }).encode("utf-8")
    with patch("urllib.request.urlopen", return_value=_fake_resp(200, body)):
        tree = github_client.get_repo_tree("owner", "repo", "main")
    assert tree is not None
    assert "src" not in tree.paths
    assert "docs" not in tree.paths
    assert "README.md" in tree.paths
