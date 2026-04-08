import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "generate_db_md.py"
DB_MD_PATH = ROOT / "DB.md"


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


def test_generator_outputs_expected_sections_in_order():
    output = _run_generator()
    assert "# DB Reference (Generated from Persisted Models)" in output
    assert "## Global State" in output
    assert "## Session State" in output
    assert output.index("## Global State") < output.index("## Session State")


def test_generator_reuses_api_shape_rendering_style_for_nested_models():
    output = _run_generator()
    global_row = re.search(r"^\| `PersistedGlobalState` \| .* \|$", output, re.MULTILINE)
    assert global_row, "Missing PersistedGlobalState row"
    assert "`main?: PersistedSessionRef {`" in global_row.group(0)
    assert "&nbsp;&nbsp;&nbsp;&nbsp;`name?:string`" in global_row.group(0)


def test_generator_renders_list_and_dict_shapes():
    output = _run_generator()
    session_row = re.search(r"^\| `PersistedSessionState` \| .* \|$", output, re.MULTILINE)
    assert session_row, "Missing PersistedSessionState row"
    assert "`poll_correct_ids?: list[string]`" in session_row.group(0)
    assert "`participants?: dict[str, PersistedParticipant {`" in session_row.group(0)
    assert "&nbsp;&nbsp;&nbsp;&nbsp;`name?:string`" in session_row.group(0)


def test_db_md_is_fresh_with_generator_output():
    generated = _run_generator()
    committed = DB_MD_PATH.read_text()
    assert generated == committed, (
        "DB.md is stale compared to generator output.\n"
        "Run: python3 scripts/generate_db_md.py --output DB.md"
    )
