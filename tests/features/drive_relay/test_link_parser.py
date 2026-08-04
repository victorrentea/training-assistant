import pytest

from railway.features.drive_relay.link_parser import InvalidDriveLink, parse_drive_url

FOLDER_ID = "1A2b3C4d5E6f7G8h9I0jKlMnOpQrStUv"


@pytest.mark.parametrize("url", [
    f"https://drive.google.com/drive/folders/{FOLDER_ID}",
    f"https://drive.google.com/drive/folders/{FOLDER_ID}?usp=sharing",
    f"https://drive.google.com/drive/folders/{FOLDER_ID}?usp=drive_link&hl=ro",
    f"https://drive.google.com/drive/u/0/folders/{FOLDER_ID}",
    f"https://drive.google.com/drive/u/2/folders/{FOLDER_ID}",
    f"https://drive.google.com/file/d/{FOLDER_ID}/view?usp=sharing",
    f"https://drive.google.com/open?id={FOLDER_ID}",
    f"https://docs.google.com/document/d/{FOLDER_ID}/edit",
    f"https://docs.google.com/spreadsheets/d/{FOLDER_ID}/edit#gid=0",
    f"https://docs.google.com/presentation/d/{FOLDER_ID}/edit",
    f"  https://drive.google.com/drive/folders/{FOLDER_ID}  ",
])
def test_extracts_id_from_every_supported_shape(url):
    assert parse_drive_url(url) == FOLDER_ID


@pytest.mark.parametrize("url", [
    "",
    "   ",
    "not a url",
    "https://example.com/drive/folders/abc",
    "https://drive.google.com/drive/folders/",
    "https://drive.google.com/drive/folders/short",
    "https://evil.com/?x=https://drive.google.com/drive/folders/" + FOLDER_ID,
    f"https://drive.google.com/drive/folders/{FOLDER_ID}'+or+'1'%3d'1",
])
def test_rejects_anything_else(url):
    with pytest.raises(InvalidDriveLink):
        parse_drive_url(url)


def test_rejects_id_with_quote_so_it_cannot_escape_the_drive_query():
    with pytest.raises(InvalidDriveLink):
        parse_drive_url("https://drive.google.com/drive/folders/abc'def'ghij")
