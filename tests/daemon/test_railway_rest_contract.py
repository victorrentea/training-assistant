"""Contract tests: docs/railway-openapi.yaml ↔ Railway FastAPI routes.

Validates that:
  1. Every operation in the spec declares a non-empty x-feature tag.
  2. Every path in the spec corresponds to an actual route decorator in the
     railway/ source tree.

To run in isolation (avoids leaking repo-root conftest browser fixtures):
  python3 -m pytest tests/daemon/test_railway_rest_contract.py -v --confcutdir=tests/daemon
"""
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parent.parent.parent
SPEC_PATH = REPO_ROOT / "docs" / "railway-openapi.yaml"
RAILWAY_DIR = REPO_ROOT / "railway"

# HTTP methods we care about in the spec
_HTTP_METHODS = {"get", "post", "put", "delete", "patch"}

# Regex: matches FastAPI route decorators, e.g.
#   @router.get("/upload/{file_id}")
#   @daemon_router.post("/api/slides/download-from-gdrive/{slug}")
_ROUTE_RE = re.compile(
    r"""@\w+\.(get|post|put|delete|patch)\(\s*["']([^"']+)["']""",
    re.IGNORECASE,
)


def _load_spec() -> dict:
    assert SPEC_PATH.exists(), (
        f"Spec not found at {SPEC_PATH}. "
        "Run the spec-generation step first."
    )
    return yaml.safe_load(SPEC_PATH.read_text())


def _collect_railway_routes() -> set[str]:
    """Return the set of fully-mounted Railway route paths from the live app.

    Using the live FastAPI app (rather than scanning decorators) means the
    paths already include router prefixes (e.g. session_host /api/{session_id})
    and we don't need fragile suffix matching.
    """
    from railway.app import app
    found: set[str] = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        if path:
            found.add(path)
    return found


def _normalize_path_params(path: str) -> str:
    """Replace all {param_name} placeholders with the generic token {param}
    so that param names don't cause mismatches."""
    return re.sub(r"\{[^}]+\}", "{param}", path)


@pytest.fixture(scope="module")
def spec() -> dict:
    return _load_spec()


@pytest.fixture(scope="module")
def railway_routes() -> set[str]:
    return _collect_railway_routes()


class TestRailwayOpenApi:
    """Validate docs/railway-openapi.yaml against Railway FastAPI source files."""

    def test_all_operations_have_x_feature(self, spec: dict):
        """Every operation in the spec must declare a non-empty x-feature."""
        missing: list[str] = []
        for path, methods in sorted(spec.get("paths", {}).items()):
            for method, details in sorted(methods.items()):
                if method.lower() not in _HTTP_METHODS:
                    continue
                if not isinstance(details, dict):
                    continue
                feature = details.get("x-feature")
                if not isinstance(feature, str) or not feature.strip():
                    missing.append(f"  {method.upper()} {path}")

        assert not missing, (
            "Operations missing x-feature metadata:\n"
            + "\n".join(missing)
            + "\n\nAdd 'x-feature: <feature_name>' to each operation in docs/railway-openapi.yaml."
        )

    def test_spec_paths_exist_in_railway_source(self, spec: dict, railway_routes: set[str]):
        """Every path in the spec must correspond to a real Railway route."""
        normalised_routes = {_normalize_path_params(r) for r in railway_routes}
        missing = sorted(
            f"  {path}"
            for path in spec.get("paths", {}).keys()
            if _normalize_path_params(path) not in normalised_routes
        )
        assert not missing, (
            "Spec paths NOT found in the live Railway app:\n"
            + "\n".join(missing)
            + "\n\nRemove the stale entries from docs/railway-openapi.yaml."
        )

    def test_every_host_auth_route_documented(self, spec: dict):
        """Every Railway route guarded by require_host_auth (i.e. callable by
        the daemon over HTTP Basic) must be documented in railway-openapi.yaml.

        Catches the silent drift the previous reverse-only check missed —
        e.g. POST /api/{session_id}/api/slides/invalidate/{slug} existed in
        the code for months without a contract entry, so it never made it
        into API.md.
        """
        # Routes that are intentionally NOT in the JSON REST contract.
        # Each entry must justify why the contract doesn't apply.
        non_rest_routes: dict[tuple[str, str], str] = {
            ("GET", "/host"):
                "HTML page (host dashboard); not a JSON REST endpoint.",
            ("GET", "/host/{param}"):
                "HTML page (session-scoped host dashboard); not a JSON REST endpoint.",
            ("GET", "/metrics"):
                "Prometheus metrics endpoint (text/plain); not part of the daemon-Railway REST contract.",
        }

        from railway.app import app
        from railway.shared.auth import require_host_auth

        def _route_uses_dep(route, target) -> bool:
            dep = getattr(route, "dependant", None)
            if dep is None:
                return False
            stack = [dep]
            while stack:
                d = stack.pop()
                if getattr(d, "call", None) is target:
                    return True
                stack.extend(getattr(d, "dependencies", []) or [])
            return False

        spec_paths: set[tuple[str, str]] = set()
        for path, methods in spec.get("paths", {}).items():
            for method in methods:
                if method.lower() in _HTTP_METHODS:
                    spec_paths.add((method.upper(), _normalize_path_params(path)))

        live_host_auth: set[tuple[str, str]] = set()
        for route in app.routes:
            methods = getattr(route, "methods", None) or set()
            path = getattr(route, "path", None)
            if not path:
                continue
            if not _route_uses_dep(route, require_host_auth):
                continue
            for method in methods:
                if method.upper() in {m.upper() for m in _HTTP_METHODS}:
                    live_host_auth.add((method.upper(), _normalize_path_params(path)))

        missing = sorted(
            (m, p) for m, p in (live_host_auth - spec_paths)
            if (m, p) not in non_rest_routes
        )
        assert not missing, (
            "Host-auth Railway routes NOT documented in docs/railway-openapi.yaml:\n"
            + "\n".join(f"  {m} {p}" for m, p in missing)
            + "\n\nAdd each missing operation to docs/railway-openapi.yaml so the"
            " daemon↔Railway contract stays exhaustive."
            "\nFor genuinely non-REST endpoints (HTML pages, metrics, etc.) add an"
            f" entry to the non_rest_routes allow-list in {__file__} with a justification."
        )
