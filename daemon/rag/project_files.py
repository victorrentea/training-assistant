"""Utilities for exposing project source files to LLM tool-use loops."""
import os
from pathlib import Path
from daemon import log

INCLUDED_EXTENSIONS = frozenset({
    ".java", ".kt", ".py", ".xml", ".properties",
    ".yml", ".yaml", ".gradle", ".groovy",
    ".json", ".sql", ".html", ".css", ".js", ".ts",
})

EXCLUDED_DIRS = frozenset({
    "target", "build", ".git", ".idea",
    "node_modules", "__pycache__", ".gradle",
})

_MAX_LINES = 500


def _resolve_safe(base_path: str, relative_path: str | None = None) -> tuple[Path, str | None]:
    """Resolve a path safely within base_path.

    Returns (resolved_path, error_string). If error_string is not None, the
    resolved_path is invalid and the error should be returned to the caller.
    """
    base = Path(os.path.realpath(base_path))
    if relative_path:
        candidate = Path(os.path.realpath(base / relative_path))
    else:
        candidate = base

    if candidate != base and not str(candidate).startswith(str(base) + os.sep):
        return candidate, f"Error: path '{relative_path}' is outside the project root"
    return candidate, None


def _is_source_file(path: Path) -> bool:
    return path.suffix in INCLUDED_EXTENSIONS


def _has_excluded_dir(path: Path, base: Path) -> bool:
    """Return True if any component of path (relative to base) is in EXCLUDED_DIRS."""
    try:
        rel = path.relative_to(base)
    except ValueError:
        return True
    return any(part in EXCLUDED_DIRS for part in rel.parts)


def _build_tree(root: Path, base: Path, indent: int = 0) -> list[str]:
    """Recursively build tree lines for root directory."""
    lines: list[str] = []
    prefix = "  " * indent

    try:
        entries = sorted(root.iterdir(), key=lambda p: (p.is_dir(), p.name))
    except PermissionError:
        return lines

    for entry in entries:
        if entry.name in EXCLUDED_DIRS:
            continue
        if entry.is_dir():
            # Only include dirs that contain at least one source file (recursively)
            sub_lines = _build_tree(entry, base, indent + 1)
            if sub_lines:
                lines.append(f"{prefix}{entry.name}/")
                lines.extend(sub_lines)
        elif entry.is_file() and _is_source_file(entry):
            lines.append(f"{prefix}{entry.name}")

    return lines


def get_project_tree(base_path: str, relative_path: str | None = None) -> str:
    """Return an indented tree of source files under the given path.

    Args:
        base_path: Absolute path to the project root.
        relative_path: Optional sub-path relative to base_path. If omitted,
                       the whole project is listed.

    Returns:
        Indented tree string, "(no source files found)" if empty, or an
        "Error: ..." string if the path is outside the project or not a directory.
    """
    target, error = _resolve_safe(base_path, relative_path)
    if error:
        return error

    if not target.is_dir():
        return f"Error: '{relative_path}' is not a directory"

    lines = _build_tree(target, Path(os.path.realpath(base_path)))
    if not lines:
        return "(no source files found)"
    return "\n".join(lines)


def read_project_file(base_path: str, relative_path: str) -> str:
    """Read a project file and return its content with line numbers.

    Args:
        base_path: Absolute path to the project root.
        relative_path: Path to the file relative to base_path.

    Returns:
        File content prefixed with line numbers ("1: first line\\n2: ..."),
        or an "Error: ..." string for any failure case.
    """
    base = Path(os.path.realpath(base_path))
    candidate = Path(os.path.realpath(base / relative_path))

    # Path traversal guard
    if not str(candidate).startswith(str(base) + os.sep) and candidate != base:
        return f"Error: path '{relative_path}' is outside the project root"

    # Excluded directory guard
    if _has_excluded_dir(candidate, base):
        return f"Error: path '{relative_path}' passes through an excluded directory"

    # Extension whitelist
    if candidate.suffix not in INCLUDED_EXTENSIONS:
        return f"Error: file extension '{candidate.suffix}' is not whitelisted"

    # Existence check
    if not candidate.exists():
        return f"Error: file '{relative_path}' does not exist"

    if not candidate.is_file():
        return f"Error: '{relative_path}' is not a file"

    # Read with line limit
    with open(candidate, encoding="utf-8", errors="replace") as fh:
        raw_lines = fh.readlines()

    if len(raw_lines) > _MAX_LINES:
        return (
            f"Error: file '{relative_path}' has {len(raw_lines)} lines, "
            f"which exceeds the {_MAX_LINES}-line limit"
        )

    numbered = "".join(f"{i + 1}: {line}" for i, line in enumerate(raw_lines))
    return numbered


PROJECT_TOOL_NAMES = {"list_project_tree", "read_project_file"}


def get_project_tools(project_folder: str | None) -> list[dict]:
    """Return Anthropic-format tool definitions for project file access.

    Returns an empty list if project_folder is None (feature disabled).
    """
    if project_folder is None:
        return []
    return [
        {
            "name": "list_project_tree",
            "description": "List the file tree of the training project's source code. Use this to discover what classes, config files, and packages exist in the project participants are working with.",
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
            "description": "Read the contents of a source file from the training project. Returns file content with line numbers. Use this to reference actual code in quiz questions or summaries.",
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


def handle_project_tool_call(tool_name: str, tool_input: dict, base_path: str) -> str:
    """Dispatch a project tool call to the appropriate handler.

    Args:
        tool_name: Name of the tool to invoke.
        tool_input: Tool input dict from the LLM.
        base_path: Absolute path to the project root.

    Returns:
        String result to pass back to the LLM as tool output.
    """
    if tool_name == "list_project_tree":
        path = tool_input.get("path")
        log.info("indexer", f"Claude browsing tree: {path or '(root)'}")
        return get_project_tree(base_path, relative_path=path)
    elif tool_name == "read_project_file":
        path = tool_input["path"]
        log.info("indexer", f"Claude reading file: {path}")
        return read_project_file(base_path, path)
    else:
        return f"Error: unknown project tool '{tool_name}'"
