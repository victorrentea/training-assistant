from railway.features.drive_relay.drive_client import DriveFile, DriveOwner
from railway.features.drive_relay.ownership import configured_identity, is_owned_by_host

EMAILS = frozenset({"victorrentea@gmail.com"})
PERMISSION_IDS = frozenset({"1234567890"})


def make_file(owners):
    return DriveFile(id="f", name="n", mime_type="application/pdf", size=1,
                     owners=tuple(owners), shortcut_target_id=None)


def owner(email="", permission_id="", display_name=""):
    return DriveOwner(email=email, permission_id=permission_id, display_name=display_name)


def check(file):
    return is_owned_by_host(file, emails=EMAILS, permission_ids=PERMISSION_IDS)


def test_accepts_matching_email():
    assert check(make_file([owner(email="victorrentea@gmail.com")])) is True


def test_email_match_is_case_insensitive():
    assert check(make_file([owner(email="VictorRentea@Gmail.com")])) is True


def test_accepts_matching_permission_id_when_email_is_redacted():
    assert check(make_file([owner(permission_id="1234567890")])) is True


def test_rejects_a_stranger():
    assert check(make_file([owner(email="someone@else.com", permission_id="999")])) is False


def test_rejects_when_no_owner_information_is_available():
    assert check(make_file([])) is False


def test_rejects_owner_with_only_a_display_name():
    assert check(make_file([owner(display_name="Victor Rentea")])) is False


def test_accepts_when_any_of_several_owners_matches():
    file = make_file([owner(email="someone@else.com"), owner(email="victorrentea@gmail.com")])
    assert check(file) is True


def test_configured_identity_reads_and_normalises_env(monkeypatch):
    monkeypatch.setenv("DRIVE_OWNER_EMAILS", " Victor@Example.com , second@example.com ")
    monkeypatch.setenv("DRIVE_OWNER_PERMISSION_IDS", "111, 222")

    emails, permission_ids = configured_identity()

    assert emails == frozenset({"victor@example.com", "second@example.com"})
    assert permission_ids == frozenset({"111", "222"})


def test_configured_identity_is_empty_when_unset(monkeypatch):
    monkeypatch.delenv("DRIVE_OWNER_EMAILS", raising=False)
    monkeypatch.delenv("DRIVE_OWNER_PERMISSION_IDS", raising=False)

    assert configured_identity() == (frozenset(), frozenset())


def test_nothing_is_owned_when_nothing_is_configured():
    file = make_file([owner(email="victorrentea@gmail.com", permission_id="1234567890")])
    assert is_owned_by_host(file, emails=frozenset(), permission_ids=frozenset()) is False
