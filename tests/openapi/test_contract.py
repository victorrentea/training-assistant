"""Contract test: ensures the committed openapi.json matches what FastAPI generates from current code."""
import json
from pathlib import Path

from railway.app import app


def test_openapi_contract_unchanged():
    committed = json.loads(Path("openapi.json").read_text())
    current = app.openapi()
    assert current == committed, (
        "OpenAPI contract has changed! Run:\n"
        "  python3 -c \"from railway.app import app; import json; print(json.dumps(app.openapi(), indent=2))\" > openapi.json\n"
        "to update openapi.json, then commit it."
    )