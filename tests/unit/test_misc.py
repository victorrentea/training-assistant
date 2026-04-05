"""Unit tests for state.py, messaging.py, and auth.py."""
import os
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from railway.shared.state import AppState, LOTR_NAMES, assign_avatar, get_avatar_filename


# ═══════════════════════════════════════════════════════════════════════
# state.py
# ═══════════════════════════════════════════════════════════════════════


class TestGetAvatarFilename:
    def test_basic(self):
        assert get_avatar_filename("Gandalf") == "gandalf.png"

    def test_spaces(self):
        assert get_avatar_filename("Tom Bombadil") == "tom-bombadil.png"

    def test_mixed_case(self):
        assert get_avatar_filename("Grima Wormtongue") == "grima-wormtongue.png"


class TestAssignAvatar:
    def test_lotr_name(self):
        s = AppState()
        avatar = assign_avatar(s, "uuid1", "Gandalf")
        assert avatar == "gandalf.png"
        assert s.participant_avatars["uuid1"] == "gandalf.png"

    def test_lotr_duplicate_allowed(self):
        s = AppState()
        assign_avatar(s, "uuid1", "Gandalf")
        avatar = assign_avatar(s, "uuid2", "Gandalf")
        assert avatar == "gandalf.png"

    def test_custom_name(self):
        s = AppState()
        avatar = assign_avatar(s, "uuid1", "CustomName")
        assert avatar.endswith(".png")
        assert avatar in [get_avatar_filename(n) for n in LOTR_NAMES]

    def test_custom_name_cached(self):
        s = AppState()
        a1 = assign_avatar(s, "uuid1", "Custom")
        a2 = assign_avatar(s, "uuid1", "Custom")
        assert a1 == a2

    def test_all_taken_fallback(self):
        s = AppState()
        # Fill all avatars
        for i, n in enumerate(LOTR_NAMES):
            s.participant_avatars[f"other-{i}"] = get_avatar_filename(n)
        avatar = assign_avatar(s, "new-uuid", "NewPerson")
        assert avatar.endswith(".png")


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
        from railway.shared.auth import require_host_auth
        from fastapi.security import HTTPBasicCredentials
        os.environ["HOST_USERNAME"] = "testuser"
        os.environ["HOST_PASSWORD"] = "testpass"
        creds = HTTPBasicCredentials(username="testuser", password="testpass")
        # Should not raise
        require_host_auth(creds)

    def test_wrong_username(self):
        from railway.shared.auth import require_host_auth
        from fastapi.security import HTTPBasicCredentials
        from fastapi import HTTPException
        os.environ["HOST_USERNAME"] = "testuser"
        os.environ["HOST_PASSWORD"] = "testpass"
        creds = HTTPBasicCredentials(username="wrong", password="testpass")
        with pytest.raises(HTTPException) as exc_info:
            require_host_auth(creds)
        assert exc_info.value.status_code == 401

    def test_wrong_password(self):
        from railway.shared.auth import require_host_auth
        from fastapi.security import HTTPBasicCredentials
        from fastapi import HTTPException
        os.environ["HOST_USERNAME"] = "testuser"
        os.environ["HOST_PASSWORD"] = "testpass"
        creds = HTTPBasicCredentials(username="testuser", password="wrong")
        with pytest.raises(HTTPException) as exc_info:
            require_host_auth(creds)
        assert exc_info.value.status_code == 401
