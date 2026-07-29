"""Guard: no native `title=` tooltips in the frontend.

The app accumulated three tooltip systems because there was nothing enforcing a
single one — and a fresh native `title=` was added as recently as the commit
that shipped the materials-zip button. `static/tooltip.js` is now the only
tooltip; this test is what keeps it that way.

`<title>Foo</title>` in a page head is an element, not an attribute, so the
pattern below deliberately does not match it.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = REPO_ROOT / "static"

# `title="` as an attribute. Requires a preceding word boundary so it does not
# fire on data-title, aria-title, or similar.
_TITLE_ATTR = re.compile(r'(?<![\w-])title\s*=\s*["\']')

# Vendored third-party assets are not ours to restyle.
_SKIP_DIRS = {"vendor", "avatars"}


def _frontend_files() -> list[Path]:
    files: list[Path] = []
    for pattern in ("*.html", "*.js"):
        for path in STATIC_DIR.rglob(pattern):
            if _SKIP_DIRS & set(path.relative_to(STATIC_DIR).parts):
                continue
            files.append(path)
    return sorted(files)


def test_frontend_files_are_discovered():
    """Guard the guard: a bad glob silently passing would be worse than useless."""
    files = _frontend_files()
    names = {f.name for f in files}
    assert {"participant.html", "host.html", "host.js"} <= names, sorted(names)


def test_no_native_title_attributes():
    offenders: list[str] = []
    for path in _frontend_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _TITLE_ATTR.search(line):
                rel = path.relative_to(REPO_ROOT)
                offenders.append(f"  {rel}:{lineno}: {line.strip()[:100]}")

    assert not offenders, (
        "Native title= tooltips found. They are slow (~500ms), tiny, and cannot be "
        "styled, which is how this app ended up with three competing tooltip looks.\n"
        "Use data-tip=\"...\" instead — static/tooltip.js picks it up automatically "
        "on every surface.\n\n" + "\n".join(offenders)
    )
