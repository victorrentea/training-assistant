import re
from pathlib import Path


def _host_css() -> str:
    return Path("static/host.css").read_text(encoding="utf-8")


def test_online_participant_name_uses_theme_text_color():
    css = _host_css()
    match = re.search(
        r"\.pax-list li\.online \.pax-name-text,\s*\.pax-list li\.online \.pax-score\s*\{([^}]*)\}",
        css,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, "Missing online participant color rule"

    block = match.group(1)
    assert "color: var(--text);" in block
    assert "#fff" not in block
