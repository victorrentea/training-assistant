import subprocess
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
