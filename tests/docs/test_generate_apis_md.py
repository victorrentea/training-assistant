import subprocess
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "generate_apis_md.py"
OPENAPI_PATH = ROOT / "docs" / "openapi.yaml"
PARTICIPANT_WS_PATH = ROOT / "docs" / "participant-ws.yaml"
HOST_WS_PATH = ROOT / "docs" / "host-ws.yaml"
API_MD_PATH = ROOT / "API.md"


def _run_generator() -> str:
    completed = subprocess.run(
        ["python3", str(SCRIPT), "--stdout"],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def _openapi_operations() -> list[tuple[str, str]]:
    spec = yaml.safe_load(OPENAPI_PATH.read_text())
    ops: list[tuple[str, str]] = []
    for path, methods in spec.get("paths", {}).items():
        for method in methods:
            if method.lower() in {"get", "post", "put", "delete", "patch"}:
                ops.append((method.upper(), path))
    return sorted(set(ops))


def _asyncapi_messages(path: Path) -> list[str]:
    spec = yaml.safe_load(path.read_text())
    refs: list[str] = []
    for channel in spec.get("channels", {}).values():
        subscribe = channel.get("subscribe", {})
        message = subscribe.get("message", {})
        for ref in message.get("oneOf", []):
            ref_value = ref.get("$ref", "")
            if ref_value.startswith("#/components/messages/"):
                refs.append(ref_value.split("/")[-1])
    return sorted(set(refs))


def test_generator_cli_outputs_feature_sections_and_examples():
    output = _run_generator()
    assert "# API Reference (Generated from Contracts)" in output
    assert "## Feature: Poll" in output
    assert "`POST /api/participant/poll/vote`" in output
    assert "`poll_opened`" in output
    assert "| Endpoint | Request | Response |" in output


def test_generator_skips_empty_subsections_and_old_none_markers():
    output = _run_generator()
    assert "- (none)" not in output


def test_generator_rest_responses_do_not_include_status_code_prefix():
    output = _run_generator()
    assert "response: `200:" not in output
    assert "`200:" not in output


def test_generator_rest_requests_do_not_include_media_type_prefix():
    output = _run_generator()
    assert "`application/json:" not in output


def test_generator_uses_dash_instead_of_none_cells():
    output = _run_generator()
    assert "`none`" not in output
    assert "| - |" in output


def test_generator_does_not_emit_redundant_enum_comments():
    output = _run_generator()
    assert "# enum:" not in output


def test_generator_renders_ws_as_table_and_omits_type_field_in_payload():
    output = _run_generator()
    assert "| Message | Payload |" in output
    activity_row = re.search(r"^\| .*`activity_updated`.*\|$", output, re.MULTILINE)
    assert activity_row, "Missing WS table row for activity_updated"
    assert "type:" not in activity_row.group(0)
    assert "current_activity:" in activity_row.group(0)


def test_participant_identity_rows_have_expected_response_shapes():
    output = _run_generator()
    register_row = re.search(r"^\| .*`POST /api/participant/register`.*\|$", output, re.MULTILINE)
    assert register_row, "Missing table row for POST /api/participant/register"
    assert "any" not in register_row.group(0)
    assert "{name: string, avatar: string}" in register_row.group(0)

    rename_row = re.search(r"^\| .*`PUT /api/participant/name`.*\|$", output, re.MULTILINE)
    assert rename_row, "Missing table row for PUT /api/participant/name"
    assert "| `{name: string}` | -" in rename_row.group(0)


def test_log_level_and_daemon_status_rows_have_expected_shapes():
    output = _run_generator()

    set_log_level_row = re.search(r"^\| .*`POST /api/log-level`.*\|$", output, re.MULTILINE)
    assert set_log_level_row, "Missing table row for POST /api/log-level"
    assert "| `{level: 'info' \\| 'debug'}` | -" in set_log_level_row.group(0)

    daemon_status_row = re.search(r"^\| .*`GET /api/daemon-status`.*\|$", output, re.MULTILINE)
    assert daemon_status_row, "Missing table row for GET /api/daemon-status"
    assert "any" not in daemon_status_row.group(0)
    assert "{code_timestamp: string \\| null}" in daemon_status_row.group(0)


def test_rest_table_notes_do_not_use_note_prefix():
    output = _run_generator()
    session_active_row = re.search(r"^\| .*`GET /api/session/active`.*\|$", output, re.MULTILINE)
    assert session_active_row, "Missing table row for GET /api/session/active"
    assert "<br>Note:" not in session_active_row.group(0)
    assert "Public endpoint: returns the active session_id or null." in session_active_row.group(0)


def test_generator_includes_all_openapi_operations():
    output = _run_generator()
    missing = []
    for method, path in _openapi_operations():
        needle = f"`{method} {path}`"
        if needle not in output:
            missing.append(needle)

    assert not missing, "Missing OpenAPI operations in generated output:\n" + "\n".join(missing)


def test_generator_includes_all_asyncapi_messages():
    output = _run_generator()
    missing = []
    for msg_name in _asyncapi_messages(PARTICIPANT_WS_PATH) + _asyncapi_messages(HOST_WS_PATH):
        needle = f"`{msg_name}`"
        if needle not in output:
            missing.append(needle)

    assert not missing, "Missing AsyncAPI messages in generated output:\n" + "\n".join(sorted(set(missing)))


def test_api_md_is_fresh_with_generator_output():
    generated = _run_generator()
    committed = API_MD_PATH.read_text()
    assert generated == committed, (
        "API.md is stale compared to generator output.\n"
        "Run: python3 scripts/generate_apis_md.py --output API.md"
    )
