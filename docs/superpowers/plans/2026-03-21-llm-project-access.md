# LLM Project File Access — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the quiz and summary generators access to the training project's source code so Claude can reference actual class names, config properties, and line numbers.

**Architecture:** A new `daemon/project_files.py` module exposes `list_project_tree` and `read_project_file` as Claude API tools. These are registered alongside the existing `search_materials` tool in the quiz generator's tool-use loop, and added to the summarizer by converting it from single-turn to a tool-use loop. Configuration flows through the existing `Config` dataclass.

**Tech Stack:** Python 3.12, Anthropic SDK (tool-use), `os`/`pathlib` for file operations.

**Spec:** `docs/superpowers/specs/2026-03-21-llm-project-access-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `daemon/project_files.py` | Create | Tree listing, file reading, tool definitions, tool call dispatch |
| `tests/test_project_files.py` | Create | Unit tests for project_files module |
| `quiz_core.py` | Modify | Add `project_folder` to Config, register project tools, handle calls in loop |
| `daemon/summarizer.py` | Modify | Convert to tool-use loop, register project tools |

---

### Task 1: Create `daemon/project_files.py` — Core Functions

**Files:**
- Create: `daemon/project_files.py`
- Test: `tests/test_project_files.py`

**Context:** This module has no external dependencies — pure Python using `os` and `pathlib`. All functions take `base_path` as a parameter (the resolved `PROJECT_FOLDER`). The module defines constants for the extension whitelist and excluded directories, shared by both tree and read functions.

- [ ] **Step 1: Write tests for `get_project_tree`**

Create `tests/test_project_files.py` with these tests:

```python
"""Unit tests for daemon/project_files.py."""
import os
import pytest
from daemon.project_files import (
    get_project_tree,
    read_project_file,
    get_project_tools,
    handle_project_tool_call,
    INCLUDED_EXTENSIONS,
    EXCLUDED_DIRS,
)


@pytest.fixture
def sample_project(tmp_path):
    """Create a realistic Java project structure."""
    # Source files
    src = tmp_path / "src" / "main" / "java" / "com" / "example"
    src.mkdir(parents=True)
    (src / "OrderService.java").write_text("public class OrderService {}\n")
    (src / "PaymentService.java").write_text("public class PaymentService {}\n")

    # Config files
    resources = tmp_path / "src" / "main" / "resources"
    resources.mkdir(parents=True)
    (resources / "application.properties").write_text("spring.datasource.url=jdbc:h2:mem:test\n")
    (resources / "application.yml").write_text("server:\n  port: 8080\n")

    # Build artifacts (should be excluded)
    target = tmp_path / "target" / "classes"
    target.mkdir(parents=True)
    (target / "OrderService.class").write_text("bytecode")

    # Git dir (should be excluded)
    git = tmp_path / ".git"
    git.mkdir()
    (git / "config").write_text("url = https://github.com/example/repo.git")

    # .idea dir (should be excluded)
    idea = tmp_path / ".idea"
    idea.mkdir()
    (idea / "workspace.xml").write_text("<xml/>")

    # Non-included extension
    (tmp_path / "README.md").write_text("# Readme")
    (tmp_path / ".env").write_text("SECRET=value")

    # Build file (included)
    (tmp_path / "pom.xml").write_text("<project/>")

    return tmp_path


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
    assert ".class" not in tree


def test_tree_excludes_git_and_idea(sample_project):
    tree = get_project_tree(str(sample_project))
    assert ".git" not in tree
    assert ".idea" not in tree


def test_tree_excludes_non_source_files(sample_project):
    tree = get_project_tree(str(sample_project))
    assert "README.md" not in tree
    assert ".env" not in tree


def test_tree_subdirectory(sample_project):
    tree = get_project_tree(str(sample_project), "src/main/java/com/example")
    assert "OrderService.java" in tree
    assert "pom.xml" not in tree


def test_tree_shows_indentation(sample_project):
    tree = get_project_tree(str(sample_project))
    lines = tree.strip().split("\n")
    # Root-level files should not be indented much
    # Nested files should have more indentation
    assert any("  " in line for line in lines), "Tree should show indented structure"
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd /Users/victorrentea/conductor/workspaces/training-assistant/sacramento
python -m pytest tests/test_project_files.py -v
```

Expected: `ModuleNotFoundError: No module named 'daemon.project_files'`

- [ ] **Step 3: Implement `get_project_tree`**

Create `daemon/project_files.py`:

```python
"""Project file browsing tools for Claude API tool-use."""
import os

INCLUDED_EXTENSIONS = frozenset({
    ".java", ".kt", ".py", ".xml", ".properties",
    ".yml", ".yaml", ".gradle", ".groovy",
    ".json", ".sql", ".html", ".css", ".js", ".ts",
})

EXCLUDED_DIRS = frozenset({
    "target", "build", ".git", ".idea",
    "node_modules", "__pycache__", ".gradle",
})


def _is_excluded_dir(name: str) -> bool:
    return name in EXCLUDED_DIRS


def _is_included_file(name: str) -> bool:
    _, ext = os.path.splitext(name)
    return ext.lower() in INCLUDED_EXTENSIONS


def get_project_tree(base_path: str, relative_path: str | None = None) -> str:
    """Return an indented tree of source files under base_path (or a subdirectory)."""
    root = os.path.join(base_path, relative_path) if relative_path else base_path
    root = os.path.realpath(root)
    base_real = os.path.realpath(base_path)

    if not root.startswith(base_real):
        return "Error: path is outside the project folder."
    if not os.path.isdir(root):
        return f"Error: '{relative_path or '.'}' is not a directory."

    lines = []
    _build_tree(root, "", lines)
    if not lines:
        return "(no source files found)"
    return "\n".join(lines)


def _build_tree(dir_path: str, prefix: str, lines: list[str]) -> None:
    """Recursively build tree lines with indentation."""
    try:
        entries = sorted(os.listdir(dir_path))
    except PermissionError:
        return

    dirs = [e for e in entries if os.path.isdir(os.path.join(dir_path, e)) and not _is_excluded_dir(e)]
    files = [e for e in entries if os.path.isfile(os.path.join(dir_path, e)) and _is_included_file(e)]

    for f in files:
        lines.append(f"{prefix}{f}")
    for d in dirs:
        lines.append(f"{prefix}{d}/")
        _build_tree(os.path.join(dir_path, d), prefix + "  ", lines)
```

- [ ] **Step 4: Run tree tests — verify they pass**

```bash
cd /Users/victorrentea/conductor/workspaces/training-assistant/sacramento
python -m pytest tests/test_project_files.py -v -k "tree"
```

Expected: All tree tests PASS.

- [ ] **Step 5: Write tests for `read_project_file`**

Append to `tests/test_project_files.py`:

```python
def test_read_file_returns_content_with_line_numbers(sample_project):
    content = read_project_file(str(sample_project), "src/main/java/com/example/OrderService.java")
    assert "1:" in content
    assert "public class OrderService" in content


def test_read_file_rejects_path_traversal(sample_project):
    result = read_project_file(str(sample_project), "../../../etc/passwd")
    assert "Error" in result


def test_read_file_rejects_excluded_dir(sample_project):
    result = read_project_file(str(sample_project), ".git/config")
    assert "Error" in result


def test_read_file_rejects_non_whitelisted_extension(sample_project):
    result = read_project_file(str(sample_project), ".env")
    assert "Error" in result
    result2 = read_project_file(str(sample_project), "README.md")
    assert "Error" in result2


def test_read_file_rejects_large_files(tmp_path):
    big = tmp_path / "Big.java"
    big.write_text("\n".join(f"line {i}" for i in range(600)))
    result = read_project_file(str(tmp_path), "Big.java")
    assert "Error" in result
    assert "500" in result


def test_read_file_nonexistent(sample_project):
    result = read_project_file(str(sample_project), "src/Missing.java")
    assert "Error" in result
```

- [ ] **Step 6: Implement `read_project_file`**

Add to `daemon/project_files.py`:

```python
MAX_FILE_LINES = 500


def read_project_file(base_path: str, relative_path: str) -> str:
    """Read a project file and return contents with line numbers."""
    base_real = os.path.realpath(base_path)
    full_path = os.path.realpath(os.path.join(base_path, relative_path))

    # Path traversal guard
    if not full_path.startswith(base_real + os.sep) and full_path != base_real:
        return "Error: path is outside the project folder."

    # Check for excluded directories in the relative path
    parts = relative_path.replace("\\", "/").split("/")
    for part in parts:
        if part in EXCLUDED_DIRS:
            return f"Error: access to '{part}/' is not allowed."

    # Extension whitelist
    if not _is_included_file(os.path.basename(full_path)):
        _, ext = os.path.splitext(full_path)
        return f"Error: file type '{ext or '(none)'}' is not in the allowed extensions list."

    if not os.path.isfile(full_path):
        return f"Error: file '{relative_path}' does not exist."

    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except (OSError, UnicodeDecodeError) as e:
        return f"Error reading file: {e}"

    if len(lines) > MAX_FILE_LINES:
        return f"Error: file has {len(lines)} lines (max {MAX_FILE_LINES}). Too large to read."

    numbered = [f"{i+1}: {line.rstrip()}" for i, line in enumerate(lines)]
    return "\n".join(numbered)
```

- [ ] **Step 7: Run all tests — verify they pass**

```bash
cd /Users/victorrentea/conductor/workspaces/training-assistant/sacramento
python -m pytest tests/test_project_files.py -v
```

Expected: All tests PASS.

- [ ] **Step 8: Commit**

```bash
git add daemon/project_files.py tests/test_project_files.py
git commit -m "feat: add project file browsing module (tree + read)"
```

---

### Task 2: Add Tool Definitions and Dispatch

**Files:**
- Modify: `daemon/project_files.py`
- Test: `tests/test_project_files.py`

**Context:** `get_project_tools()` returns the Anthropic SDK tool definition dicts. `handle_project_tool_call()` dispatches tool calls and logs them. These follow the exact format used by `search_materials` in `quiz_core.py:393-405`.

- [ ] **Step 1: Write tests for `get_project_tools` and `handle_project_tool_call`**

Append to `tests/test_project_files.py`:

```python
def test_get_project_tools_returns_empty_when_no_folder():
    tools = get_project_tools(None)
    assert tools == []


def test_get_project_tools_returns_two_tools():
    tools = get_project_tools("/some/path")
    assert len(tools) == 2
    names = {t["name"] for t in tools}
    assert names == {"list_project_tree", "read_project_file"}
    # Verify Anthropic SDK format
    for tool in tools:
        assert "input_schema" in tool
        assert tool["input_schema"]["type"] == "object"


def test_handle_tool_call_list_tree_root(sample_project):
    """Most common invocation: no path argument (empty dict)."""
    result = handle_project_tool_call(
        "list_project_tree", {}, str(sample_project)
    )
    assert "OrderService.java" in result
    assert "pom.xml" in result


def test_handle_tool_call_list_tree_subdir(sample_project):
    result = handle_project_tool_call(
        "list_project_tree", {"path": "src/main/java/com/example"}, str(sample_project)
    )
    assert "OrderService.java" in result


def test_handle_tool_call_read_file(sample_project):
    result = handle_project_tool_call(
        "read_project_file",
        {"path": "src/main/java/com/example/OrderService.java"},
        str(sample_project),
    )
    assert "public class OrderService" in result


def test_handle_tool_call_unknown_tool(sample_project):
    result = handle_project_tool_call("unknown_tool", {}, str(sample_project))
    assert "Error" in result
```

- [ ] **Step 2: Implement `get_project_tools` and `handle_project_tool_call`**

Add to `daemon/project_files.py`:

```python
def get_project_tools(project_folder: str | None) -> list[dict]:
    """Return Claude API tool definitions. Empty list if project_folder is None."""
    if not project_folder:
        return []
    return [
        {
            "name": "list_project_tree",
            "description": (
                "List the file tree of the training project's source code. "
                "Use this to discover what classes, config files, and packages "
                "exist in the project participants are working with."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Optional subdirectory path relative to project root. Omit to list the entire project.",
                    }
                },
                "required": [],
            },
        },
        {
            "name": "read_project_file",
            "description": (
                "Read the contents of a source file from the training project. "
                "Returns file content with line numbers. Use this to reference "
                "actual code in quiz questions or summaries."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to project root (e.g., 'src/main/java/com/example/OrderService.java')",
                    }
                },
                "required": ["path"],
            },
        },
    ]


PROJECT_TOOL_NAMES = {"list_project_tree", "read_project_file"}


def handle_project_tool_call(tool_name: str, tool_input: dict, base_path: str) -> str:
    """Dispatch a project tool call. Returns the result string."""
    if tool_name == "list_project_tree":
        path = tool_input.get("path")
        print(f"[info] Claude is browsing project tree: {path or '(root)'}...")
        return get_project_tree(base_path, path)
    elif tool_name == "read_project_file":
        path = tool_input["path"]
        print(f"[info] Claude is reading project file: {path}...")
        return read_project_file(base_path, path)
    else:
        return f"Error: unknown project tool '{tool_name}'"
```

- [ ] **Step 3: Run tests — verify they pass**

```bash
cd /Users/victorrentea/conductor/workspaces/training-assistant/sacramento
python -m pytest tests/test_project_files.py -v
```

Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add daemon/project_files.py tests/test_project_files.py
git commit -m "feat: add tool definitions and dispatch for project file tools"
```

---

### Task 3: Integrate into Quiz Generation (`quiz_core.py`)

**Files:**
- Modify: `quiz_core.py` — Config dataclass (~line 39), `config_from_env()` (~line 67), `generate_quiz()` (~line 386), system prompt (~line 296)

**Context:** The existing tool-use loop in `generate_quiz()` (lines 410–444) already handles `search_materials`. We add project tools to the same `tools` array and add a branch in the loop to dispatch them. The loop structure stays the same — it already iterates over all `tool_use` blocks.

- [ ] **Step 1: Add `project_folder` to Config dataclass**

In `quiz_core.py`, find the Config dataclass (around line 39). Add `project_folder` as an optional field at the end:

```python
# After the existing fields (topic, session_folder, session_notes):
    project_folder: Optional[str] = None
```

Add `Optional` to the imports from `typing` if not already present.

- [ ] **Step 2: Load `PROJECT_FOLDER` in `config_from_env()`**

In `config_from_env()` (around line 67–87), add after the other env var reads:

```python
    project_folder = os.environ.get("PROJECT_FOLDER")
```

And include `project_folder=project_folder` in the `Config(...)` constructor call.

- [ ] **Step 3: Update system prompt with project tool instructions**

In `_SYSTEM_PROMPT` (around line 296), append a new section after the `search_materials` instructions:

```python
# Add to the end of _SYSTEM_PROMPT, before the closing triple-quote:
"""

## Project Source Code
If `list_project_tree` and `read_project_file` tools are available, you have access to the training project's source code. When the transcript discusses specific classes, patterns, or configurations, use these tools to find the actual code and reference real class names, method signatures, and line numbers in your quiz questions. Start with `list_project_tree` to discover the project structure, then `read_project_file` for specific files mentioned in the transcript.
"""
```

- [ ] **Step 4: Register project tools in `generate_quiz()`**

In `generate_quiz()` (around line 393), after the `tools = [...]` definition for `search_materials`, add:

```python
    from daemon.project_files import get_project_tools, handle_project_tool_call, PROJECT_TOOL_NAMES
    tools.extend(get_project_tools(config.project_folder))
```

- [ ] **Step 5: Handle project tool calls in the tool-use loop**

In the tool-use loop (around line 420–440), modify the tool call handling. Currently it assumes all tool calls are `search_materials`. Change to:

```python
        tool_results = []
        for tool_call in tool_use_blocks:
            if tool_call.name == "search_materials":
                search_results = search_materials(tool_call.input["query"])
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_call.id,
                    "content": json.dumps(search_results)
                })
            elif tool_call.name in PROJECT_TOOL_NAMES:
                result = handle_project_tool_call(
                    tool_call.name, tool_call.input, config.project_folder
                )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_call.id,
                    "content": result
                })
            else:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_call.id,
                    "content": f"Error: unknown tool '{tool_call.name}'"
                })
```

- [ ] **Step 6: Run existing quiz tests to verify no regressions**

```bash
cd /Users/victorrentea/conductor/workspaces/training-assistant/sacramento
python -m pytest test_quiz_core.py -v
```

Expected: All existing tests PASS.

- [ ] **Step 7: Commit**

```bash
git add quiz_core.py
git commit -m "feat: integrate project file tools into quiz generation"
```

---

### Task 4: Convert Summarizer to Tool-Use Loop (`daemon/summarizer.py`)

**Files:**
- Modify: `daemon/summarizer.py` — `generate_summary()` function

**Context:** Currently `generate_summary()` makes a single `create_message()` call without tools (around line 97). Convert it to a tool-use loop following the exact pattern from `quiz_core.py:410-444`. The response parsing (lines 105–148) stays the same — it just runs after the loop breaks on `"end_turn"`. The return type remains `Optional[list[dict]]`.

- [ ] **Step 1: Add project tool imports**

At the top of `daemon/summarizer.py`, add:

```python
from daemon.project_files import get_project_tools, handle_project_tool_call, PROJECT_TOOL_NAMES
```

- [ ] **Step 2: Update the system prompt**

In `_SUMMARY_SYSTEM_PROMPT` (around line 25), append:

```python
# Add to the end of the prompt:
"""

## Project Source Code
If `list_project_tree` and `read_project_file` tools are available, use them to find relevant source files when the transcript mentions specific classes, patterns, or configurations. Include specific class/method references in your key points (e.g., 'the @Transactional annotation in PaymentService.java:34').
"""
```

- [ ] **Step 3: Convert `generate_summary()` to tool-use loop**

Replace the single `create_message()` call and response parsing with a tool-use loop. The key change: wrap the call in a `while True` loop and only parse JSON from the final response.

Find the current `create_message()` call (around line 97–102) and replace with:

```python
    # Build tools list
    tools = get_project_tools(config.project_folder)

    # Messages for multi-turn tool use
    messages = [{"role": "user", "content": user_message}]

    # Tool-use loop (or single-turn if no tools)
    # max_tokens bumped from 1024 to 2048 to accommodate tool-use round-trips
    create_kwargs = dict(
        api_key=config.api_key,
        model=config.model,
        max_tokens=2048,
        system=_SUMMARY_SYSTEM_PROMPT,
        messages=messages,
    )
    if tools:
        create_kwargs["tools"] = tools

    while True:
        response = create_message(**create_kwargs)
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "tool_use":
            tool_use_blocks = [c for c in response.content if c.type == "tool_use"]
            tool_results = []
            for tool_call in tool_use_blocks:
                if tool_call.name in PROJECT_TOOL_NAMES:
                    result = handle_project_tool_call(
                        tool_call.name, tool_call.input, config.project_folder
                    )
                else:
                    result = f"Error: unknown tool '{tool_call.name}'"
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_call.id,
                    "content": result,
                })
            messages.append({"role": "user", "content": tool_results})
            create_kwargs["messages"] = messages
            continue
        else:
            break

    # Response parsing continues here (same as before)
```

The existing response parsing code (checking `response.content[0].type == "text"`, stripping code fences, parsing JSON) stays exactly as-is after the loop.

- [ ] **Step 4: Run existing tests**

```bash
cd /Users/victorrentea/conductor/workspaces/training-assistant/sacramento
python -m pytest test_e2e_quiz_summary.py -v -k "summary" 2>&1 | head -40
```

If no summary-specific tests exist, verify the module at least imports cleanly:

```bash
cd /Users/victorrentea/conductor/workspaces/training-assistant/sacramento
python -c "from daemon.summarizer import generate_summary; print('OK')"
```

Expected: No import errors.

- [ ] **Step 5: Commit**

```bash
git add daemon/summarizer.py
git commit -m "feat: add project file tools to summary generation"
```

---

### Task 5: Load `PROJECT_FOLDER` in Daemon Entry Point

**Files:**
- Modify: `training_daemon.py` — config loading section (~line 192)

**Context:** `config_from_env()` in `quiz_core.py` already reads `PROJECT_FOLDER` (added in Task 3). The daemon just needs to log whether it's configured so the trainer knows the feature is active.

- [ ] **Step 1: Add startup log for `PROJECT_FOLDER`**

In `training_daemon.py`, after the config is loaded (around line 192–195), add a log line:

```python
    if config.project_folder:
        print(f"[info] Project folder configured: {config.project_folder}")
        if not os.path.isdir(config.project_folder):
            print(f"[warn] PROJECT_FOLDER does not exist: {config.project_folder}")
    else:
        print("[info] PROJECT_FOLDER not set — project file tools disabled")
```

- [ ] **Step 2: Verify daemon imports cleanly**

```bash
cd /Users/victorrentea/conductor/workspaces/training-assistant/sacramento
python -c "import training_daemon; print('OK')" 2>&1 | head -5
```

Expected: No import errors (the daemon may exit due to lock file or missing env, but no import crash).

- [ ] **Step 3: Commit**

```bash
git add training_daemon.py
git commit -m "feat: log PROJECT_FOLDER status on daemon startup"
```

---

### Task 6: End-to-End Smoke Test

**Files:**
- Test: `tests/test_project_files.py` (append)

**Context:** Verify the full tool-use integration works by testing that `generate_quiz()` includes project tools when `config.project_folder` is set. This doesn't call the real Claude API — it mocks `create_message` to verify the tools are passed correctly.

- [ ] **Step 1: Write integration test**

Append to `tests/test_project_files.py`:

```python
from unittest.mock import patch, MagicMock
from quiz_core import Config, generate_quiz


def _make_config_with_project(tmp_path):
    """Create a Config with project_folder set."""
    # Create a minimal project
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

    # Mock create_message to capture the tools argument
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

    # Verify project tools were included
    tools = captured_kwargs.get("tools", [])
    tool_names = {t["name"] for t in tools}
    assert "list_project_tree" in tool_names
    assert "read_project_file" in tool_names
    assert "search_materials" in tool_names
```

- [ ] **Step 2: Run integration test**

```bash
cd /Users/victorrentea/conductor/workspaces/training-assistant/sacramento
python -m pytest tests/test_project_files.py::test_generate_quiz_includes_project_tools -v
```

Expected: PASS.

- [ ] **Step 3: Run full test suite to verify no regressions**

```bash
cd /Users/victorrentea/conductor/workspaces/training-assistant/sacramento
python -m pytest tests/test_project_files.py test_quiz_core.py -v
```

Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_project_files.py
git commit -m "test: add integration test for project tools in quiz generation"
```
