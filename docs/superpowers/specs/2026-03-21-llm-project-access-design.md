# LLM Project File Access for Quiz & Summary Generation

## Problem

The quiz and summary generators use transcription text and RAG-indexed materials (slides, books) but have no access to the actual training project's source code. This means generated content can't reference real class names, configuration properties, or code patterns that participants are working with during the workshop.

## Solution

Add two tools — `list_project_tree` and `read_project_file` — to the daemon's Claude API tool-use calls for both quiz generation and summary generation. When `PROJECT_FOLDER` is set, Claude can browse and read the training project's source files on demand, grounding generated content in the actual codebase.

## Configuration

New environment variable:

| Variable | Default | Purpose |
|----------|---------|---------|
| `PROJECT_FOLDER` | (unset) | Absolute path to training project source root |

When unset, project file tools are not registered — existing behavior unchanged.

**Config integration:** Add `project_folder: Optional[str] = None` field to the `Config` dataclass in `quiz_core.py`. Load it in `config_from_env()` from `os.environ.get("PROJECT_FOLDER")`. Pass `config.project_folder` to all project file functions — never re-read the env var directly.

## New Module: `daemon/project_files.py`

### Functions

- `get_project_tree(base_path: str, relative_path: str | None = None) -> str`
  - Returns indented tree of source files under the given path
  - Included extensions: `.java`, `.kt`, `.py`, `.xml`, `.properties`, `.yml`, `.yaml`, `.gradle`, `.groovy`, `.json`, `.sql`, `.html`, `.css`, `.js`, `.ts`
  - Excluded directories: `target/`, `build/`, `.git/`, `.idea/`, `node_modules/`, `__pycache__/`, `.gradle/`
  - Output format: indented text similar to the Unix `tree` command

- `read_project_file(base_path: str, relative_path: str) -> str`
  - Reads a file relative to `PROJECT_FOLDER`, returns content with line numbers
  - Path traversal guard: resolves path and verifies it stays under `base_path`
  - Enforces the same extension whitelist as `list_project_tree`
  - Rejects paths through excluded directories (`.git/`, `target/`, etc.) — prevents reading `.git/config` or similar
  - File size cap: returns error if file exceeds 500 lines
  - Returns error for binary/non-text files

- `get_project_tools(config: dict) -> list[dict]`
  - Returns Claude API tool definitions for `list_project_tree` and `read_project_file`
  - Returns empty list if `PROJECT_FOLDER` not configured

- `handle_project_tool_call(tool_name: str, tool_input: dict, base_path: str) -> str`
  - Dispatches tool calls to the appropriate function
  - Returns string result for inclusion in tool_result messages

### Tool Definitions (Claude API format)

```json
{
  "name": "list_project_tree",
  "description": "List the file tree of the training project's source code. Use this to discover what classes, config files, and packages exist in the project participants are working with.",
  "input_schema": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "description": "Optional subdirectory path relative to project root. Omit to list the entire project."
      }
    },
    "required": []
  }
}
```

```json
{
  "name": "read_project_file",
  "description": "Read the contents of a source file from the training project. Returns file content with line numbers. Use this to reference actual code in quiz questions or summaries.",
  "input_schema": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "description": "File path relative to project root (e.g., 'src/main/java/com/example/OrderService.java')"
      }
    },
    "required": ["path"]
  }
}
```

## Integration: Quiz Generation (`quiz_core.py`)

**Changes:**
1. Import `get_project_tools` and `handle_project_tool_call` from `daemon.project_files`
2. In `generate_quiz()`, append project tools to the existing `tools` array (alongside `search_materials`)
3. In the tool-use loop, add a branch to handle `list_project_tree` and `read_project_file` tool calls via `handle_project_tool_call()`
4. Update the system prompt to instruct Claude to use the project tools:

> *"You have access to the training project's source code via `list_project_tree` and `read_project_file`. When the transcript discusses specific classes, patterns, or configurations, use these tools to find the actual code and reference real class names, method signatures, and line numbers in your quiz questions."*

No structural changes to the tool-use loop — it already handles multiple tools.

## Integration: Summary Generation (`daemon/summarizer.py`)

**Changes:**
1. Convert from single-turn prompt to a tool-use loop (same pattern as `generate_quiz()`):
   - Wrap the existing `create_message()` call in a `while True` loop
   - Check `response.stop_reason == "tool_use"` — if so, process tool calls, append results, re-prompt
   - Break on `"end_turn"` — then parse JSON from the final response (same parsing logic as today)
   - Return type stays `Optional[list[dict]]` — unchanged
   - Consider bumping `max_tokens` from 1024 to 2048 to accommodate tool-use overhead
2. Register project tools when `PROJECT_FOLDER` is set
3. Update system prompt to encourage code references in summaries:

> *"When summarizing technical points, use `list_project_tree` and `read_project_file` to find relevant source files and include specific class/method references (e.g., 'the `@Transactional` annotation in `PaymentService.java:34`')."*

## Security

- **Path traversal prevention**: `os.path.realpath()` on the resolved path, verify it starts with the resolved `PROJECT_FOLDER`. Resolves symlinks — a symlink to `/etc/passwd` is correctly rejected.
- **Excluded directory enforcement**: both `list_project_tree` and `read_project_file` reject paths through `.git/`, `target/`, `build/`, `.idea/`, `node_modules/`, `__pycache__/`, `.gradle/`
- **Extension whitelist**: both listing and reading enforce the same extension whitelist — prevents reading `.env`, `.class`, or other sensitive/binary files
- **Read-only**: no write, delete, or execute tools
- **File size cap**: 500-line limit per file read to avoid context bloat

## Logging

Project tool calls should produce log output consistent with existing patterns:
- `[info] Claude is browsing project tree: {path}...`
- `[info] Claude is reading project file: {path}...`

## Files Changed

| File | Change |
|------|--------|
| `daemon/project_files.py` | New module — tree listing, file reading, tool definitions |
| `quiz_core.py` | Register project tools, handle tool calls in loop |
| `daemon/summarizer.py` | Add tool-use loop, register project tools |
| `training_daemon.py` | Load `PROJECT_FOLDER` from env/config |

## Testing

- Unit tests for `project_files.py`: tree generation, file reading, path traversal rejection, size cap
- Integration test: quiz generation with a mock project folder verifies tool calls work end-to-end
