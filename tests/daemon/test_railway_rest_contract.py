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
    """Scan all Python files under railway/ and return the set of decorator paths."""
    found: set[str] = set()
    for py_file in sorted(RAILWAY_DIR.rglob("*.py")):
        text = py_file.read_text(encoding="utf-8", errors="replace")
        for _method, path in _ROUTE_RE.findall(text):
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
        """Every path in the spec must match a @router.<method>() decorator in railway/."""
        # Build a normalised set of known route paths for quick lookup
        normalised_routes = {_normalize_path_params(r) for r in railway_routes}

        missing: list[str] = []
        for path in sorted(spec.get("paths", {}).keys()):
            normalised_path = _normalize_path_params(path)

            # Accept either an exact match or a suffix match (router prefix cases)
            found = (
                normalised_path in normalised_routes
                or any(
                    route == normalised_path or route.endswith(normalised_path)
                    for route in normalised_routes
                )
            )
            if not found:
                missing.append(f"  {path}  (normalised: {normalised_path})")

        assert not missing, (
            "Spec paths NOT found as route decorators in railway/ source:\n"
            + "\n".join(missing)
            + "\n\nEither add the missing route to railway/ or remove the stale entry from docs/railway-openapi.yaml."
        )
