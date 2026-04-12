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
    global_block = re.search(
        r"### `PersistedGlobalState`\n\n(?P<body>.*?)(?:\n### |\Z)",
        output,
        re.DOTALL,
    )
    assert global_block, "Missing PersistedGlobalState section"
    body = global_block.group("body")
    assert "main?: PersistedSessionRef {" in body
    assert "name?:string" in body


def test_generator_renders_list_and_dict_shapes():
    output = _run_generator()
    session_block = re.search(
        r"### `PersistedSessionState`\n\n(?P<body>.*?)(?:\n### |\Z)",
        output,
        re.DOTALL,
    )
    assert session_block, "Missing PersistedSessionState section"
    body = session_block.group("body")
    assert "participants?: dict[str, PersistedParticipant {" in body
    assert "name?:string" in body
    assert "poll?: PersistedPollState {" in body
    assert "correct_ids?:list[string]" in body
    assert "wordcloud?: PersistedWordCloudState {" in body
    assert "codereview?: PersistedCodeReviewState {" in body
    assert "debate?: PersistedDebateState {" in body


def test_generator_does_not_use_markdown_tables():
    output = _run_generator()
    assert "| Structure | Shape |" not in output
    assert not re.search(r"^\|.+\|$", output, re.MULTILINE)


def test_db_md_is_fresh_with_generator_output():
    generated = _run_generator()
    committed = DB_MD_PATH.read_text()
    assert generated == committed, (
        "DB.md is stale compared to generator output.\n"
        "Run: python3 scripts/generate_db_md.py --output DB.md"
    )
