"""Guard: every inline <script> block in static/*.html must be valid JS.

`static/fx.html` once shipped with an unescaped apostrophe inside a JS string
that closed the string early and syntax-errored the whole IIFE — the page
never executed a single line. `curl` still returned `200 text/html` (the page
markup itself was fine), and the only test touching the route
(`tests/daemon/test_fx_participant.py::TestPage`) asserted exactly that
envelope: status 200, `content-type: text/html`. Nothing checked that the
script inside actually parsed. A human opening the page is what caught it.

This test extracts every inline (non-`src`) <script> block from every
`static/*.html` file and runs `node --check` on it, so a broken script fails
CI with the file, the line, and the syntax error — the same signal a human
would have seen in the browser console, just earlier and automated.
"""
import re
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = REPO_ROOT / "static"

# Vendored/generated assets are not ours to author correct JS in.
_SKIP_DIRS = {"vendor", "avatars"}

# `<script ...>...</script>`, non-greedy body, case-insensitive tag name.
_SCRIPT_RE = re.compile(r"<script([^>]*)>(.*?)</script>", re.IGNORECASE | re.DOTALL)
_SRC_ATTR_RE = re.compile(r'(?<![\w-])src\s*=', re.IGNORECASE)
_TYPE_ATTR_RE = re.compile(r'type\s*=\s*["\']([^"\']*)["\']', re.IGNORECASE)

# Script `type`s that hold real JavaScript. Anything else (application/json,
# text/template, ...) is not JS and node would rightly refuse to parse it.
_MODULE_TYPES = {"module"}
_CLASSIC_JS_TYPES = {"", "text/javascript", "application/javascript", "application/ecmascript"}


def _html_files() -> list[Path]:
    files = []
    for path in STATIC_DIR.glob("*.html"):
        if _SKIP_DIRS & set(path.relative_to(STATIC_DIR).parts):
            continue
        files.append(path)
    return sorted(files)


def _inline_scripts(path: Path):
    """Yield (line_number, is_module, source) for each inline <script> in
    `path`. `line_number` is the 1-based line where the script body starts,
    so it lines up with what an editor would show."""
    text = path.read_text(encoding="utf-8")
    for match in _SCRIPT_RE.finditer(text):
        attrs, body = match.groups()
        if _SRC_ATTR_RE.search(attrs):
            continue  # external script, nothing inline to check
        type_match = _TYPE_ATTR_RE.search(attrs)
        script_type = (type_match.group(1) if type_match else "").strip().lower()
        if script_type in _MODULE_TYPES:
            is_module = True
        elif script_type in _CLASSIC_JS_TYPES:
            is_module = False
        else:
            continue  # e.g. application/json — not JS, node shouldn't parse it
        line_number = text[:match.start(2)].count("\n") + 1
        yield line_number, is_module, body


def _node_check(source: str, is_module: bool) -> str | None:
    """Run `node --check` on `source`. Returns the error text, or None if it
    parses cleanly. `.mjs`/`.js` extensions tell node whether to parse the
    file as an ES module (needed for the `type="module"` blocks, which use
    top-level `import`) or a classic script."""
    suffix = ".mjs" if is_module else ".js"
    with tempfile.NamedTemporaryFile(suffix=suffix, mode="w", encoding="utf-8", delete=False) as f:
        f.write(source)
        tmp_path = Path(f.name)
    try:
        result = subprocess.run(
            ["node", "--check", str(tmp_path)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return None
        return result.stderr.strip()
    finally:
        tmp_path.unlink(missing_ok=True)


def test_html_files_with_inline_scripts_are_discovered():
    """Guard the guard: a bad glob silently finding nothing would be worse
    than useless.

    Pinned to participant.html — the page every attendee loads, and by far the
    most inline JS in the repo. (It used to be pinned to fx.html, which was the
    original case for this guard; that page died with the secret FX link, and a
    guard anchored to a deleted file is a guard that checks nothing.)
    """
    found = {p.name for p in _html_files()}
    assert "participant.html" in found, sorted(found)
    scripted = {p.name for p in _html_files() if list(_inline_scripts(p))}
    assert "participant.html" in scripted, (
        "participant.html has no discovered inline <script> — the extraction "
        "regex regressed, and the syntax check below would silently check nothing."
    )


def test_inline_scripts_are_syntactically_valid():
    offenders: list[str] = []
    for path in _html_files():
        for line_number, is_module, source in _inline_scripts(path):
            error = _node_check(source, is_module)
            if error:
                rel = path.relative_to(REPO_ROOT)
                offenders.append(f"{rel}:{line_number}\n{error}")

    assert not offenders, (
        "Inline <script> with a JS syntax error found. A page like this can "
        "still return 200 text/html — the markup is fine, only the script "
        "inside is dead — which is exactly how fx.html shipped broken for "
        "one commit undetected.\n\n" + "\n\n".join(offenders)
    )


@pytest.mark.parametrize("broken", [
    "const say = function () { status.textContent = 'don't touch this'; };",
])
def test_the_guard_actually_catches_a_syntax_error(broken):
    """Reproduces the original fx.html defect directly: an unescaped
    apostrophe inside a single-quoted JS string closes the string early and
    breaks the rest of the block. Proves this guard would have caught it."""
    error = _node_check(broken, is_module=False)
    assert error is not None
    assert "SyntaxError" in error
