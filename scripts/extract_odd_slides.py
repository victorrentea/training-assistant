#!/usr/bin/env python3
"""
Extract odd-numbered slides (1, 3, 5, ...) from a cached Railway PDF
and write a new PDF with only those pages.

Usage:
    python3 scripts/extract_odd_slides.py <slug> [output.pdf]

The slug is fetched from /api/status (cached slide) or passed explicitly.
Credentials are read from ~/.training-assistants-secrets.env.
"""

import ssl
import sys
import urllib.parse
import urllib.request
from io import BytesIO
from pathlib import Path

_SSL_CTX = ssl.create_default_context()
try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX.check_hostname = False
    _SSL_CTX.verify_mode = ssl.CERT_NONE

# ---------------------------------------------------------------------------
# Load env from secrets file
# ---------------------------------------------------------------------------

SECRETS_FILE = Path.home() / ".training-assistants-secrets.env"


def _load_secrets() -> dict[str, str]:
    env: dict[str, str] = {}
    if not SECRETS_FILE.exists():
        return env
    for line in SECRETS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()
    return env


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch(url: str, username: str, password: str) -> bytes:
    import base64
    req = urllib.request.Request(url)
    creds = base64.b64encode(f"{username}:{password}".encode()).decode()
    req.add_header("Authorization", f"Basic {creds}")
    with urllib.request.urlopen(req, context=_SSL_CTX, timeout=60) as resp:
        return resp.read()


def _get_session_id() -> str:
    import json
    # session_id is owned by the local daemon; Railway no longer exposes it publicly.
    with urllib.request.urlopen("http://localhost:1234/api/session/active", timeout=10) as resp:
        data = json.loads(resp.read())
    sid = data.get("session_id", "")
    if not sid:
        raise RuntimeError("No active session on the local daemon (is the daemon running?)")
    return sid


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    secrets = _load_secrets()
    base_url = secrets.get("WORKSHOP_SERVER_URL", "https://interact.victorrentea.ro").rstrip("/")
    username = secrets.get("HOST_USERNAME", "host")
    password = secrets.get("HOST_PASSWORD", "")

    if len(sys.argv) < 2:
        # auto-detect slug from active session
        import json
        import urllib.request
        with urllib.request.urlopen(f"{base_url}/api/status", context=_SSL_CTX, timeout=10) as resp:
            status = json.loads(resp.read())
        slug = (status.get("slides_current") or {}).get("slug", "")
        if not slug:
            print("ERROR: no active cached slide; pass slug as argument", file=sys.stderr)
            sys.exit(1)
        print(f"Auto-detected slug: {slug}")
    else:
        slug = sys.argv[1]

    output_path = Path(sys.argv[2]) if len(sys.argv) >= 3 else Path(f"odd_slides_{slug[:8]}.pdf")

    # Resolve session_id
    session_id = _get_session_id()

    # Download PDF
    download_url = f"{base_url}/{session_id}/api/slides/download/{slug}"
    print(f"Downloading from {download_url} ...")
    pdf_bytes = _fetch(download_url, username, password)
    print(f"Downloaded {len(pdf_bytes) / 1024:.0f} KB")

    # Extract odd pages
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        print("ERROR: pypdf not installed. Run: pip install pypdf", file=sys.stderr)
        sys.exit(1)

    reader = PdfReader(BytesIO(pdf_bytes))
    total = len(reader.pages)
    print(f"Total pages: {total}")

    writer = PdfWriter()
    odd_pages = list(range(0, total, 2))  # 0-indexed: 0, 2, 4, ... → slides 1, 3, 5, ...
    for i in odd_pages:
        writer.add_page(reader.pages[i])

    output_path.write_bytes(b"")
    with open(output_path, "wb") as f:
        writer.write(f)

    print(f"Wrote {len(odd_pages)} odd slides → {output_path}")


if __name__ == "__main__":
    main()
