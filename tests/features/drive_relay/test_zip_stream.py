import io
import zipfile

import pytest

from railway.features.drive_relay.zip_stream import TransferCapExceeded, stream_zip

CAP = 10 * 1024 * 1024


def read_back(chunks):
    return zipfile.ZipFile(io.BytesIO(b"".join(chunks)))


def test_produces_a_readable_archive():
    archive = read_back(stream_zip([("a.txt", [b"hello ", b"world"])], max_bytes=CAP))

    assert archive.testzip() is None
    assert archive.read("a.txt") == b"hello world"


def test_preserves_folder_structure_and_order():
    entries = [("Intro.pdf", [b"1"]), ("Day 2/Lab.pdf", [b"2"]), ("Day 2/Sol/A.pdf", [b"3"])]

    archive = read_back(stream_zip(entries, max_bytes=CAP))

    assert archive.namelist() == ["Intro.pdf", "Day 2/Lab.pdf", "Day 2/Sol/A.pdf"]


def test_preserves_unicode_names():
    archive = read_back(stream_zip([("Note — ünïcode.txt", [b"x"])], max_bytes=CAP))

    assert archive.read("Note — ünïcode.txt") == b"x"


def test_stores_without_compression():
    archive = read_back(stream_zip([("a.bin", [b"x" * 5000])], max_bytes=CAP))

    assert archive.infolist()[0].compress_type == zipfile.ZIP_STORED


def test_memory_stays_flat_for_large_files():
    """A 4 MB file must never be buffered whole — yields stay chunk-sized."""
    chunks = list(stream_zip([("big.bin", (b"x" * 65536 for _ in range(64)))], max_bytes=CAP))

    assert max(len(c) for c in chunks) < 200 * 1024
    assert read_back(chunks).read("big.bin") == b"x" * (65536 * 64)


def test_empty_archive_is_still_valid():
    archive = read_back(stream_zip([], max_bytes=CAP))

    assert archive.namelist() == []


def test_raises_once_payload_exceeds_the_cap():
    entries = [("big.bin", (b"x" * 1024 for _ in range(200)))]

    with pytest.raises(TransferCapExceeded):
        list(stream_zip(entries, max_bytes=100 * 1024))


def test_cap_counts_across_entries_not_per_entry():
    entries = [("a.bin", [b"x" * 60_000]), ("b.bin", [b"y" * 60_000])]

    with pytest.raises(TransferCapExceeded):
        list(stream_zip(entries, max_bytes=100_000))


def test_stays_under_the_cap_without_raising():
    chunks = list(stream_zip([("a.bin", [b"x" * 90_000])], max_bytes=100_000))

    assert read_back(chunks).read("a.bin") == b"x" * 90_000
