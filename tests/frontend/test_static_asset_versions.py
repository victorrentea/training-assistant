"""Versioned <script src="/static/x.js?v=HASH"> tags must carry the file's current hash.

Railway serves /static without Cache-Control, so after a hot-deploy the browser
reloads the (no-cache) HTML but may keep a heuristically cached JS file. A page
built against the new script then calls the old one and breaks — the AI % chart
did exactly that on 2026-09-28. The query string makes a changed file a new URL;
this test keeps it honest.
"""
import hashlib
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "static"
PAGES = ["participant.html", "host.html"]
# Scripts whose API changes together with the page: they must be versioned.
MUST_BE_VERSIONED = {"aishare-chart.js", "tooltip.js"}
TAG = re.compile(r'<script[^>]+src="/static/([\w./-]+\.js)(?:\?v=([0-9a-f]+))?"')


def _short_hash(name: str) -> str:
    return hashlib.md5((STATIC / name).read_bytes()).hexdigest()[:8]


@pytest.mark.parametrize("page", PAGES)
def test_versioned_scripts_match_their_content(page):
    for name, version in TAG.findall((STATIC / page).read_text()):
        if name in MUST_BE_VERSIONED:
            assert version, f"{page}: /static/{name} must be referenced as ?v={_short_hash(name)}"
        if version:
            assert version == _short_hash(name), (
                f"{page}: /static/{name} changed — bump its tag to ?v={_short_hash(name)}")
