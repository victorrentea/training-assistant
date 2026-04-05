"""
Production health check — loads participant and host pages in a headless browser,
verifies key UI elements render and no JavaScript errors occur.

Usage: python3 healthcheck.py [BASE_URL]
Exit 0 = healthy, Exit 1 = failure detected
"""
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "https://interact.victorrentea.ro"

# Load credentials from the shared secrets file (fallback to legacy local paths)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_candidates = [
    os.environ.get("TRAINING_ASSISTANTS_SECRETS_FILE", ""),
    os.path.expanduser("~/.training-assistants-secrets.env"),
    os.path.join(SCRIPT_DIR, "secrets.env"),
]
for secrets_path in _candidates:
    if secrets_path and os.path.exists(secrets_path):
        for line in open(secrets_path):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
        break

HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "host")

failures = []
results = []


def check_page(browser, name, url, elements, auth=None):
    """Load a page, check for JS errors and verify UI elements."""
    js_errors = []
    start = time.time()

    context_opts = {}
    if auth:
        context_opts["http_credentials"] = {"username": auth[0], "password": auth[1]}

    context = browser.new_context(**context_opts)
    page = context.new_page()
    page.on("pageerror", lambda e: js_errors.append(str(e)))

    try:
        response = page.goto(url, timeout=15000, wait_until="networkidle")
        elapsed = time.time() - start

        # Check HTTP status
        if response is None or response.status >= 500:
            status = response.status if response else "no response"
            failures.append(f"{name}: HTTP {status}")
            results.append(f"  FAIL {name}: HTTP {status} [{elapsed:.2f}s]")
            return

        if response.status == 401 and auth:
            # Auth failed but server is up — not a health issue
            results.append(f"  WARN {name}: HTTP 401 (auth failed, server OK) [{elapsed:.2f}s]")
            return

        if response.status != 200:
            failures.append(f"{name}: HTTP {response.status}")
            results.append(f"  FAIL {name}: HTTP {response.status} [{elapsed:.2f}s]")
            return

        # Check JS errors
        if js_errors:
            failures.append(f"{name}: JS errors: {js_errors}")
            results.append(f"  FAIL {name}: {len(js_errors)} JS error(s) [{elapsed:.2f}s]")
            for err in js_errors[:3]:
                results.append(f"       {err[:200]}")
            return

        # Check UI elements
        missing = []
        for selector in elements:
            try:
                loc = page.locator(selector)
                if loc.count() == 0:
                    missing.append(selector)
            except Exception:
                missing.append(selector)

        if missing:
            failures.append(f"{name}: missing elements: {missing}")
            results.append(f"  FAIL {name}: {len(missing)} missing element(s) [{elapsed:.2f}s]")
            for sel in missing:
                results.append(f"       missing: {sel}")
            return

        results.append(f"  OK   {name}: {len(elements)} elements verified [{elapsed:.2f}s]")

    except Exception as e:
        elapsed = time.time() - start
        failures.append(f"{name}: {e}")
        results.append(f"  FAIL {name}: {str(e)[:200]} [{elapsed:.2f}s]")
    finally:
        context.close()


PARTICIPANT_ELEMENTS = [
    "#main-screen",
    "#display-name",
    "#pax-count",
    "#content",
    "#emoji-bar",
    "#version-tag",
]

HOST_ELEMENTS = [
    ".host-columns",
    ".tab-bar",
    "#tab-poll",
    "#tab-content-poll",
    "#create-btn",
    "#center-qr",
    "#pax-count",
    "#participant-link",
    "#mode-badge",
    "#ws-badge",
    "#version-tag",
]


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        check_page(browser, "Participant page", f"{BASE_URL}/",
                   PARTICIPANT_ELEMENTS)

        check_page(browser, "Host page", f"{BASE_URL}/host",
                   HOST_ELEMENTS, auth=(HOST_USER, HOST_PASS))

        browser.close()

    ts = time.strftime("%H:%M:%S")
    if failures:
        print(f"FAIL - Production issues detected {ts}")
        for r in results:
            print(r)
        sys.exit(1)
    else:
        print(f"OK - Production healthy {ts}")
        for r in results:
            print(r)
        sys.exit(0)


if __name__ == "__main__":
    main()
