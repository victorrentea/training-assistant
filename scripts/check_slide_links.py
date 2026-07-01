#!/usr/bin/env python3
"""Verify every Google Slides deck linked on the public slides page still
exports to a real PDF, and email an alert via Resend if any are broken.

Why this exists: when a source PPTX grows too large, Google Drive stops
exporting it to PDF. That failure is *content-based*, not a clean HTTP error
-- Google returns an HTML error page (or a 404 for a removed/private deck),
so a naive "is it HTTP 200?" monitor would miss it. This script therefore
validates three things per link: HTTP 200, Content-Type application/pdf, and
the leading "%PDF-" magic bytes.

Designed to run as a scheduled GitHub Actions job (no local scheduler).
Locally: `python3 scripts/check_slide_links.py` prints a report. Set
RESEND_API_KEY in the environment to also send the alert email.

Exit code: 0 if all decks are healthy, 1 if any deck is broken.
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

SLIDES_PAGE = os.environ.get("SLIDES_PAGE_URL", "https://victorrentea.ro/slides/")
ALERT_EMAIL = os.environ.get("ALERT_EMAIL", "victorrentea@gmail.com")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
EMAIL_FROM = os.environ.get("ALERT_FROM", "Slides Link Monitor <onboarding@resend.dev>")
RUN_URL = os.environ.get("RUN_URL", "")  # set by the workflow to the Actions run URL

TIMEOUT = 30
MIN_PDF_BYTES = 1024  # a valid deck is always larger than this
USER_AGENT = (
    "slides-link-monitor/1.0 "
    "(+https://github.com/victorrentea/training-assistant)"
)

# Matches the <a href="...export/pdf">Title</a> anchors on the slides page.
# DOTALL because the title sits on the line after the opening tag.
LINK_RE = re.compile(
    r'<a[^>]+href="(?P<url>https://docs\.google\.com/presentation/d/[^"]+/export/pdf)"'
    r"[^>]*>(?P<title>.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)


def _request(url: str, max_bytes: int | None = None):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        body = resp.read(max_bytes) if max_bytes else resp.read()
        return resp.status, resp.headers, body


def discover_decks(page_html: str) -> list[tuple[str, str]]:
    """Return unique (title, url) pairs, preserving first-seen order."""
    decks: dict[str, str] = {}
    for m in LINK_RE.finditer(page_html):
        url = m.group("url")
        title = re.sub(r"<[^>]+>", "", m.group("title"))  # strip nested tags
        title = re.sub(r"\s+", " ", html.unescape(title)).strip()
        decks.setdefault(url, title or url)
    return [(title, url) for url, title in decks.items()]


def check_deck(deck: tuple[str, str]) -> dict:
    title, url = deck
    try:
        status, headers, body = _request(url, max_bytes=2048)
    except urllib.error.HTTPError as e:
        return {"title": title, "url": url, "ok": False, "reason": f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001 - report any transport failure verbatim
        return {"title": title, "url": url, "ok": False, "reason": f"{type(e).__name__}: {e}"}

    ctype = headers.get("Content-Type", "")
    clen = headers.get("Content-Length")
    is_pdf = ctype.lower().startswith("application/pdf") and body[:5] == b"%PDF-"

    if status != 200:
        reason = f"HTTP {status}"
    elif not is_pdf:
        reason = f"not a PDF (Content-Type '{ctype or 'n/a'}', starts {body[:8]!r})"
    elif clen is not None and clen.isdigit() and int(clen) < MIN_PDF_BYTES:
        reason = f"PDF suspiciously small ({clen} bytes)"
    else:
        return {"title": title, "url": url, "ok": True, "reason": "OK"}

    return {"title": title, "url": url, "ok": False, "reason": reason}


def send_alert(broken: list[dict], total: int) -> None:
    if not RESEND_API_KEY:
        print("RESEND_API_KEY not set -- skipping email (report above).", file=sys.stderr)
        return

    n = len(broken)
    lines = [f"  - {b['title']}: {b['reason']}\n    {b['url']}" for b in broken]
    text = (
        f"{n} of {total} slide deck link(s) on {SLIDES_PAGE} are FAILING.\n\n"
        "A deck fails this check when Google no longer returns a valid PDF -- "
        "typically because the source PPTX grew too large to export, or the deck "
        "was removed / made private.\n\n"
        "Broken decks:\n" + "\n".join(lines) + "\n"
    )
    if RUN_URL:
        text += f"\nGitHub Actions run: {RUN_URL}\n"

    rows = "".join(
        f'<tr><td style="padding:4px 8px"><a href="{b["url"]}">{html.escape(b["title"])}</a></td>'
        f'<td style="padding:4px 8px;color:#b00">{html.escape(b["reason"])}</td></tr>'
        for b in broken
    )
    html_body = (
        f"<h2>🚨 {n} of {total} slide deck link(s) failing</h2>"
        f'<p>Checked from <a href="{SLIDES_PAGE}">{SLIDES_PAGE}</a>. '
        "A deck fails when Google no longer returns a valid PDF export "
        "(source PPTX too large, or deck removed / made private).</p>"
        '<table style="border-collapse:collapse" border="1">'
        "<tr><th>Deck</th><th>Reason</th></tr>" + rows + "</table>"
        + (f'<p><a href="{RUN_URL}">View the GitHub Actions run</a></p>' if RUN_URL else "")
    )

    payload = json.dumps(
        {
            "from": EMAIL_FROM,
            "to": [ALERT_EMAIL],
            "subject": f"🚨 Slides link check: {n} deck(s) failing",
            "text": text,
            "html": html_body,
        }
    ).encode()
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        print(f"Alert email sent to {ALERT_EMAIL} (Resend HTTP {resp.status}).")


def write_summary(results: list[dict], broken: list[dict]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    lines = [
        "## Slides link check",
        "",
        f"Checked **{len(results)}** decks from {SLIDES_PAGE} — "
        f"**{len(broken)}** failing.",
        "",
        "| Status | Deck | Reason |",
        "| --- | --- | --- |",
    ]
    for r in results:
        mark = "✅" if r["ok"] else "❌"
        lines.append(f"| {mark} | [{r['title']}]({r['url']}) | {r['reason']} |")
    with open(summary_path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main() -> int:
    try:
        _, _, page = _request(SLIDES_PAGE)
    except Exception as e:  # noqa: BLE001
        print(f"FATAL: could not fetch {SLIDES_PAGE}: {e}", file=sys.stderr)
        # Treat an unreachable index page as a failure worth emailing about.
        send_alert(
            [{"title": "slides index page", "url": SLIDES_PAGE, "reason": str(e)}], 0
        )
        return 1

    decks = discover_decks(page.decode("utf-8", "replace"))
    if not decks:
        print(f"FATAL: no deck links found on {SLIDES_PAGE}", file=sys.stderr)
        send_alert(
            [{"title": "no deck links found", "url": SLIDES_PAGE, "reason": "0 links parsed"}], 0
        )
        return 1

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(check_deck, decks))

    # On-demand delivery test: inject a synthetic broken deck so the alert
    # email path runs even when every real deck is healthy. Triggered by the
    # workflow's "simulate_failure" dispatch input.
    if os.environ.get("SIMULATE_FAILURE", "").lower() in ("1", "true", "yes"):
        results.append(
            {
                "title": "TEST — simulated failure (ignore)",
                "url": SLIDES_PAGE,
                "ok": False,
                "reason": "simulated failure to test email delivery",
            }
        )

    broken = [r for r in results if not r["ok"]]
    for r in results:
        print(f"{'OK  ' if r['ok'] else 'FAIL'}  {r['title']:<28} {r['reason']}")
    print(f"\n{len(results) - len(broken)}/{len(results)} decks OK, {len(broken)} broken.")

    write_summary(results, broken)

    if broken:
        send_alert(broken, len(results))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
