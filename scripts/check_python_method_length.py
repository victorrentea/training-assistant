#!/usr/bin/env python3
"""Fail when Python functions/methods exceed a max LOC threshold.

Supports a baseline file to allow existing violations while blocking regressions.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".context",
    ".playwright-mcp",
}


@dataclass(frozen=True)
class Violation:
    path: str
    qualname: str
    lineno: int
    lines: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check that Python functions/methods do not exceed max LOC."
    )
    parser.add_argument("paths", nargs="*", help="Python files to check")
    parser.add_argument("--max-lines", type=int, default=60)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument(
        "--staged",
        action="store_true",
        help="Check only staged Python files (git diff --cached).",
    )
    return parser.parse_args()


def discover_python_files(paths: list[str], staged: bool) -> list[Path]:
    if staged:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            check=True,
            text=True,
            capture_output=True,
        )
        files = [
            Path(line.strip())
            for line in result.stdout.splitlines()
            if line.strip().endswith(".py")
        ]
        return [p for p in files if p.is_file()]

    if paths:
        files = [Path(p) for p in paths if p.endswith(".py")]
        return [p for p in files if p.is_file()]

    files: list[Path] = []
    for path in Path(".").rglob("*.py"):
        if any(part in DEFAULT_EXCLUDED_DIRS for part in path.parts):
            continue
        if path.is_file():
            files.append(path)
    return files


def load_baseline(path: Path | None) -> dict[tuple[str, str], int]:
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[tuple[str, str], int] = {}
    for item in data.get("violations", []):
        out[(item["path"], item["qualname"])] = int(item["lines"])
    return out


def collect_violations(file_path: Path, max_lines: int) -> list[Violation]:
    source = file_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines()

    violations: list[Violation] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._check_node(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._check_node(node)

        def _check_node(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            self.stack.append(node.name)
            start = node.lineno
            end = node.end_lineno or node.lineno

            excluded_docstring: set[int] = set()
            if node.body:
                first = node.body[0]
                if (
                    isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)
                ):
                    ds_start = first.lineno
                    ds_end = first.end_lineno or first.lineno
                    excluded_docstring = set(range(ds_start, ds_end + 1))

            code_lines = 0
            for line_no in range(start, end + 1):
                if line_no in excluded_docstring:
                    continue
                stripped = lines[line_no - 1].strip()
                if not stripped or stripped.startswith("#"):
                    continue
                code_lines += 1

            if code_lines > max_lines:
                violations.append(
                    Violation(
                        path=str(file_path),
                        qualname=".".join(self.stack),
                        lineno=node.lineno,
                        lines=code_lines,
                    )
                )

            self.generic_visit(node)
            self.stack.pop()

    Visitor().visit(tree)
    return violations


def main() -> int:
    args = parse_args()
    files = discover_python_files(args.paths, staged=args.staged)

    if not files:
        print("No Python files to check.")
        return 0

    baseline = load_baseline(args.baseline)

    all_violations: list[Violation] = []
    for path in files:
        try:
            all_violations.extend(collect_violations(path, args.max_lines))
        except SyntaxError as exc:
            print(f"ERROR: failed to parse {path}: {exc}")
            return 2

    new_or_grown: list[tuple[Violation, int | None]] = []
    for violation in all_violations:
        key = (violation.path, violation.qualname)
        baseline_lines = baseline.get(key)
        if baseline_lines is None:
            new_or_grown.append((violation, None))
        elif violation.lines > baseline_lines:
            new_or_grown.append((violation, baseline_lines))

    if not new_or_grown:
        print(
            f"OK: Python function/method length <= {args.max_lines} LOC (baseline respected)."
        )
        return 0

    print("ERROR: Found Python function/methods above the allowed LOC threshold:")
    for violation, baseline_lines in sorted(
        new_or_grown, key=lambda item: (item[0].path, item[0].lineno)
    ):
        if baseline_lines is None:
            print(
                f"  {violation.path}:{violation.lineno} {violation.qualname} "
                f"has {violation.lines} LOC (> {args.max_lines})"
            )
        else:
            print(
                f"  {violation.path}:{violation.lineno} {violation.qualname} "
                f"grew to {violation.lines} LOC (baseline {baseline_lines}, max {args.max_lines})"
            )

    print("Refactor the function or update the baseline intentionally.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
