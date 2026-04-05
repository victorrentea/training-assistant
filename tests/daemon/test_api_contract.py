"""Contract tests — verify daemon FastAPI routes match the OpenAPI snapshot in docs/.

Strategy:
  1. Build the daemon app and extract its OpenAPI schema via app.openapi().
  2. Filter to /api/ routes only (skip static, WS, proxy catch-all).
  3. Clean FastAPI noise (422 validation errors, internal schemas).
  4. Compare against the committed snapshot docs/openapi-generated.yaml.
  5. If they differ, the test fails with a helpful diff and regeneration command.

To regenerate the snapshot after intentional changes:
  python3 -m tests.daemon.test_api_contract --regenerate
"""
import copy
import sys
import warnings
from pathlib import Path

import pytest
import yaml

DOCS_DIR = Path(__file__).parent.parent.parent / "docs"
SNAPSHOT_PATH = DOCS_DIR / "openapi-generated.yaml"


def _extract_clean_openapi() -> dict:
    """Build daemon app, extract OpenAPI, and filter to API-only routes."""
    warnings.filterwarnings("ignore")
    from daemon.host_server import create_app

    app = create_app("http://test-backend")
    openapi = copy.deepcopy(app.openapi())

    # Keep only /api/ routes, exclude catch-all proxy
    filtered_paths = {}
    for path, methods in openapi["paths"].items():
        if not path.startswith("/api/"):
            continue
        if "{path" in path:
            continue
        filtered_paths[path] = methods

    openapi["paths"] = filtered_paths

    # Remove internal schemas
    schemas = openapi.get("components", {}).get("schemas", {})
    for internal in ["HTTPValidationError", "ValidationError"]:
        schemas.pop(internal, None)

    # Clean up 422 validation error responses (FastAPI noise)
    for path, methods in openapi["paths"].items():
        for method, details in methods.items():
            if isinstance(details, dict) and "responses" in details:
                details["responses"].pop("422", None)

    return openapi


def _load_snapshot() -> dict:
    """Load the committed OpenAPI snapshot from disk."""
    return yaml.safe_load(SNAPSHOT_PATH.read_text())


def _regenerate():
    """Regenerate the OpenAPI snapshot file."""
    openapi = _extract_clean_openapi()
    with open(SNAPSHOT_PATH, "w") as f:
        yaml.dump(openapi, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    path_count = len(openapi["paths"])
    schema_count = len(openapi.get("components", {}).get("schemas", {}))
    print(f"Regenerated {SNAPSHOT_PATH} ({path_count} paths, {schema_count} schemas)")


# ── Tests ────────────────────────────────────────────────────────────────────


class TestOpenApiSnapshot:
    """The daemon's generated OpenAPI must match the committed snapshot."""

    @pytest.fixture(scope="module")
    def live_openapi(self):
        return _extract_clean_openapi()

    @pytest.fixture(scope="module")
    def snapshot_openapi(self):
        assert SNAPSHOT_PATH.exists(), (
            f"Snapshot not found at {SNAPSHOT_PATH}. "
            f"Run: python3 -m tests.daemon.test_api_contract --regenerate"
        )
        return _load_snapshot()

    def test_paths_match(self, live_openapi, snapshot_openapi):
        """Every path in the snapshot must exist in live, and vice versa."""
        live_paths = set(live_openapi["paths"].keys())
        snap_paths = set(snapshot_openapi["paths"].keys())

        missing_from_live = snap_paths - live_paths
        extra_in_live = live_paths - snap_paths

        errors = []
        if missing_from_live:
            errors.append(
                "Paths in snapshot but MISSING from daemon:\n"
                + "\n".join(f"  - {p}" for p in sorted(missing_from_live))
            )
        if extra_in_live:
            errors.append(
                "Paths in daemon but NOT in snapshot (new endpoints?):\n"
                + "\n".join(f"  + {p}" for p in sorted(extra_in_live))
            )

        assert not errors, (
            "\n".join(errors)
            + "\n\nRegenerate: python3 -m tests.daemon.test_api_contract --regenerate"
        )

    def test_methods_match(self, live_openapi, snapshot_openapi):
        """Every path must have the same HTTP methods in both."""
        errors = []
        common_paths = set(live_openapi["paths"]) & set(snapshot_openapi["paths"])

        for path in sorted(common_paths):
            live_methods = {m.lower() for m in live_openapi["paths"][path] if m.lower() in ("get", "post", "put", "delete", "patch")}
            snap_methods = {m.lower() for m in snapshot_openapi["paths"][path] if m.lower() in ("get", "post", "put", "delete", "patch")}
            if live_methods != snap_methods:
                errors.append(f"  {path}: live={sorted(live_methods)}, snapshot={sorted(snap_methods)}")

        assert not errors, (
            "Method mismatches:\n" + "\n".join(errors)
            + "\n\nRegenerate: python3 -m tests.daemon.test_api_contract --regenerate"
        )

    def test_request_schemas_match(self, live_openapi, snapshot_openapi):
        """Request body schemas must match between live and snapshot."""
        errors = []
        common_paths = set(live_openapi["paths"]) & set(snapshot_openapi["paths"])

        for path in sorted(common_paths):
            for method in live_openapi["paths"][path]:
                if method.lower() not in ("get", "post", "put", "delete", "patch"):
                    continue
                live_op = live_openapi["paths"][path].get(method, {})
                snap_op = snapshot_openapi["paths"][path].get(method, {})

                live_body = live_op.get("requestBody")
                snap_body = snap_op.get("requestBody")

                if live_body != snap_body:
                    errors.append(f"  {method.upper()} {path}: request body schema differs")

        assert not errors, (
            "Request schema mismatches:\n" + "\n".join(errors)
            + "\n\nRegenerate: python3 -m tests.daemon.test_api_contract --regenerate"
        )

    def test_component_schemas_match(self, live_openapi, snapshot_openapi):
        """Pydantic model schemas in components must match."""
        live_schemas = live_openapi.get("components", {}).get("schemas", {})
        snap_schemas = snapshot_openapi.get("components", {}).get("schemas", {})

        missing = set(snap_schemas) - set(live_schemas)
        extra = set(live_schemas) - set(snap_schemas)
        errors = []

        if missing:
            errors.append("Schemas in snapshot but MISSING from daemon:\n"
                          + "\n".join(f"  - {s}" for s in sorted(missing)))
        if extra:
            errors.append("Schemas in daemon but NOT in snapshot:\n"
                          + "\n".join(f"  + {s}" for s in sorted(extra)))

        # Check field-level differences for common schemas
        for name in sorted(set(live_schemas) & set(snap_schemas)):
            if live_schemas[name] != snap_schemas[name]:
                errors.append(f"  Schema '{name}' differs (fields changed)")

        assert not errors, (
            "\n".join(errors)
            + "\n\nRegenerate: python3 -m tests.daemon.test_api_contract --regenerate"
        )


# ── CLI: regenerate snapshot ─────────────────────────────────────────────────

if __name__ == "__main__":
    if "--regenerate" in sys.argv:
        _regenerate()
    else:
        print("Usage: python3 -m tests.daemon.test_api_contract --regenerate")
        sys.exit(1)
