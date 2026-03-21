"""Tests for daemon/project_files.py — TDD first pass."""
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from daemon.project_files import get_project_tree, read_project_file, get_project_tools, handle_project_tool_call, PROJECT_TOOL_NAMES


@pytest.fixture
def sample_project(tmp_path):
    """Create a realistic Java Maven project structure."""
    # Source files (included)
    java_dir = tmp_path / "src" / "main" / "java" / "com" / "example"
    java_dir.mkdir(parents=True)
    (java_dir / "OrderService.java").write_text(
        "package com.example;\n\npublic class OrderService {\n    // order logic\n}\n"
    )
    (java_dir / "PaymentService.java").write_text(
        "package com.example;\n\npublic class PaymentService {\n    // payment logic\n}\n"
    )

    resources_dir = tmp_path / "src" / "main" / "resources"
    resources_dir.mkdir(parents=True)
    (resources_dir / "application.properties").write_text("server.port=8080\n")
    (resources_dir / "application.yml").write_text("server:\n  port: 8080\n")

    (tmp_path / "pom.xml").write_text("<project></project>\n")

    # Build artifacts (excluded via target/)
    target_dir = tmp_path / "target" / "classes"
    target_dir.mkdir(parents=True)
    (target_dir / "OrderService.class").write_bytes(b"\xca\xfe\xba\xbe")

    # VCS metadata (excluded via .git/)
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("[core]\n    repositoryformatversion = 0\n")

    # IDE metadata (excluded via .idea/)
    idea_dir = tmp_path / ".idea"
    idea_dir.mkdir()
    (idea_dir / "workspace.xml").write_text("<project></project>\n")

    # Non-whitelisted extensions
    (tmp_path / "README.md").write_text("# My Project\n")
    (tmp_path / ".env").write_text("SECRET=hunter2\n")

    return tmp_path


# --- get_project_tree tests ---

def test_tree_includes_source_files(sample_project):
    tree = get_project_tree(str(sample_project))
    assert "OrderService.java" in tree
    assert "PaymentService.java" in tree
    assert "application.properties" in tree
    assert "application.yml" in tree
    assert "pom.xml" in tree


def test_tree_excludes_build_artifacts(sample_project):
    tree = get_project_tree(str(sample_project))
    assert "target" not in tree
    assert "OrderService.class" not in tree


def test_tree_excludes_git_and_idea(sample_project):
    tree = get_project_tree(str(sample_project))
    assert ".git" not in tree
    assert ".idea" not in tree
    assert "workspace.xml" not in tree


def test_tree_excludes_non_source_files(sample_project):
    tree = get_project_tree(str(sample_project))
    assert "README.md" not in tree
    assert ".env" not in tree


def test_tree_subdirectory(sample_project):
    tree = get_project_tree(str(sample_project), "src/main/java/com/example")
    assert "OrderService.java" in tree
    assert "PaymentService.java" in tree
    # resources are outside this subdir
    assert "application.properties" not in tree
    assert "pom.xml" not in tree


def test_tree_shows_indentation(sample_project):
    tree = get_project_tree(str(sample_project))
    lines = tree.splitlines()
    # At least one indented line should exist (subdirectory content)
    indented = [l for l in lines if l.startswith("  ")]
    assert len(indented) > 0


def test_tree_dirs_suffixed_with_slash(sample_project):
    tree = get_project_tree(str(sample_project))
    # Directories that contain source files should appear with trailing /
    assert "src/" in tree


def test_tree_empty_returns_message(tmp_path):
    # No source files at all
    result = get_project_tree(str(tmp_path))
    assert result == "(no source files found)"


def test_tree_relative_path_outside_project_returns_error(sample_project):
    result = get_project_tree(str(sample_project), "../../../etc")
    assert result.lower().startswith("error")


def test_tree_relative_path_not_a_directory_returns_error(sample_project):
    result = get_project_tree(str(sample_project), "pom.xml")
    assert result.lower().startswith("error")


# --- read_project_file tests ---

def test_read_file_returns_content_with_line_numbers(sample_project):
    content = read_project_file(
        str(sample_project), "src/main/java/com/example/OrderService.java"
    )
    assert "1:" in content
    assert "package com.example;" in content


def test_read_file_rejects_path_traversal(sample_project):
    result = read_project_file(str(sample_project), "../../../etc/passwd")
    assert result.lower().startswith("error")


def test_read_file_rejects_excluded_dir(sample_project):
    result = read_project_file(str(sample_project), ".git/config")
    assert result.lower().startswith("error")


def test_read_file_rejects_non_whitelisted_extension(sample_project):
    result_md = read_project_file(str(sample_project), "README.md")
    assert result_md.lower().startswith("error")

    result_env = read_project_file(str(sample_project), ".env")
    assert result_env.lower().startswith("error")


def test_read_file_rejects_large_files(sample_project):
    large_file = sample_project / "BigFile.java"
    large_file.write_text("\n".join(f"// line {i}" for i in range(1, 601)))
    result = read_project_file(str(sample_project), "BigFile.java")
    assert result.lower().startswith("error")
    assert "500" in result


def test_read_file_nonexistent(sample_project):
    result = read_project_file(str(sample_project), "src/main/java/com/example/Ghost.java")
    assert result.lower().startswith("error")


# --- get_project_tools tests ---

def test_get_project_tools_returns_empty_when_no_folder():
    tools = get_project_tools(None)
    assert tools == []

def test_get_project_tools_returns_two_tools():
    tools = get_project_tools("/some/path")
    assert len(tools) == 2
    names = {t["name"] for t in tools}
    assert names == {"list_project_tree", "read_project_file"}
    for tool in tools:
        assert "input_schema" in tool
        assert tool["input_schema"]["type"] == "object"


# --- handle_project_tool_call tests ---

def test_handle_tool_call_list_tree_root(sample_project):
    """Most common invocation: no path argument (empty dict)."""
    result = handle_project_tool_call("list_project_tree", {}, str(sample_project))
    assert "OrderService.java" in result
    assert "pom.xml" in result

def test_handle_tool_call_list_tree_subdir(sample_project):
    result = handle_project_tool_call("list_project_tree", {"path": "src/main/java/com/example"}, str(sample_project))
    assert "OrderService.java" in result

def test_handle_tool_call_read_file(sample_project):
    result = handle_project_tool_call("read_project_file", {"path": "src/main/java/com/example/OrderService.java"}, str(sample_project))
    assert "public class OrderService" in result

def test_handle_tool_call_unknown_tool(sample_project):
    result = handle_project_tool_call("unknown_tool", {}, str(sample_project))
    assert "Error" in result


# --- integration test: generate_quiz includes project tools ---

from quiz_core import Config, generate_quiz


def _make_config_with_project(tmp_path):
    """Create a Config with project_folder set."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "App.java").write_text("public class App {}\n")

    return Config(
        folder=tmp_path,
        minutes=30,
        server_url="http://localhost:8000",
        api_key="test-key",
        model="test-model",
        dry_run=False,
        host_username="host",
        host_password="pass",
        project_folder=str(tmp_path),
    )


def test_generate_quiz_includes_project_tools(tmp_path):
    """Verify that generate_quiz registers project tools when project_folder is set."""
    config = _make_config_with_project(tmp_path)

    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    mock_response.content = [MagicMock(type="text", text='{"question":"test?","options":["a","b"],"correct_indices":[0]}')]
    mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)

    captured_kwargs = {}

    def capture_create_message(**kwargs):
        captured_kwargs.update(kwargs)
        return mock_response

    with patch("quiz_core.create_message", side_effect=capture_create_message):
        with patch("quiz_core.search_materials", return_value=[]):
            generate_quiz("some transcript text", config)

    tools = captured_kwargs.get("tools", [])
    tool_names = {t["name"] for t in tools}
    assert "list_project_tree" in tool_names
    assert "read_project_file" in tool_names
    assert "search_materials" in tool_names
