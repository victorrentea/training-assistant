"""Build a zip archive as a byte stream, with nothing buffered and nothing on disk.

stdlib `zipfile` can write into an unseekable stream: it detects the missing
`seek` and emits data descriptors on its own. So we hand it a sink that just
accumulates writes, and drain that sink after every chunk we push in. Zip-format
correctness (data descriptors, zip64, unicode flags) stays inside the stdlib
instead of in hand-rolled header code.

STORED, not DEFLATE: course materials are already PDF/PPTX/zip, so compressing
them burns CPU on a shared box for no size win.
"""
from __future__ import annotations

import io
import zipfile
from collections.abc import Iterable, Iterator


class TransferCapExceeded(RuntimeError):
    """The archive payload grew past the caller's byte cap."""


class _Sink(io.RawIOBase):
    """An unseekable write target that hands its bytes back on demand."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def write(self, data) -> int:  # type: ignore[override]
        self._buffer += data
        return len(data)

    def writable(self) -> bool:
        return True

    def drain(self) -> bytes:
        data = bytes(self._buffer)
        self._buffer.clear()
        return data


def stream_zip(
    entries: Iterable[tuple[str, Iterable[bytes]]],
    max_bytes: int,
) -> Iterator[bytes]:
    """Yield the bytes of a zip holding ``entries`` as (archive_path, chunks).

    Raises TransferCapExceeded as soon as the payload passes ``max_bytes``. The
    caller is mid-response by then, so this cuts the download off rather than
    turning into a status code — the pre-check in the router is what produces a
    clean refusal.
    """
    sink = _Sink()
    written = 0

    with zipfile.ZipFile(sink, "w", zipfile.ZIP_STORED) as archive:
        for archive_path, chunks in entries:
            with archive.open(archive_path, "w", force_zip64=True) as target:
                for chunk in chunks:
                    written += len(chunk)
                    if written > max_bytes:
                        raise TransferCapExceeded(
                            f"Transfer exceeded {max_bytes} bytes"
                        )
                    target.write(chunk)
                    payload = sink.drain()
                    if payload:
                        yield payload
            payload = sink.drain()
            if payload:
                yield payload

    payload = sink.drain()
    if payload:
        yield payload
