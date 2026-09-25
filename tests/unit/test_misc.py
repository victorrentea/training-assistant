"""Unit tests for auth.py."""

import os

import pytest


# ═══════════════════════════════════════════════════════════════════════
# auth.py
# ═══════════════════════════════════════════════════════════════════════


class TestAuth:
    @pytest.fixture(autouse=True)
    def restore_auth_env(self):
        orig_user = os.environ.get("HOST_USERNAME")
        orig_pass = os.environ.get("HOST_PASSWORD")
        yield
        if orig_user is None:
            os.environ.pop("HOST_USERNAME", None)
        else:
            os.environ["HOST_USERNAME"] = orig_user
        if orig_pass is None:
            os.environ.pop("HOST_PASSWORD", None)
        else:
            os.environ["HOST_PASSWORD"] = orig_pass

    def test_correct_credentials(self):
        from fastapi.security import HTTPBasicCredentials

        from railway.shared.auth import require_host_auth

        os.environ["HOST_USERNAME"] = "testuser"
        os.environ["HOST_PASSWORD"] = "testpass"
        creds = HTTPBasicCredentials(username="testuser", password="testpass")
        # Should not raise
        require_host_auth(creds)

    def test_wrong_username(self):
        from fastapi import HTTPException
        from fastapi.security import HTTPBasicCredentials

        from railway.shared.auth import require_host_auth

        os.environ["HOST_USERNAME"] = "testuser"
        os.environ["HOST_PASSWORD"] = "testpass"
        creds = HTTPBasicCredentials(username="wrong", password="testpass")
        with pytest.raises(HTTPException) as exc_info:
            require_host_auth(creds)
        assert exc_info.value.status_code == 401

    def test_wrong_password(self):
        from fastapi import HTTPException
        from fastapi.security import HTTPBasicCredentials

        from railway.shared.auth import require_host_auth

        os.environ["HOST_USERNAME"] = "testuser"
        os.environ["HOST_PASSWORD"] = "testpass"
        creds = HTTPBasicCredentials(username="testuser", password="wrong")
        with pytest.raises(HTTPException) as exc_info:
            require_host_auth(creds)
        assert exc_info.value.status_code == 401
