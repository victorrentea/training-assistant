#!/usr/bin/env python3
"""Generate persisted data structure markdown from daemon Pydantic models."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from daemon.persisted_models import (
    PersistedGlobalState,
    PersistedSessionMeta,
    PersistedSessionState,
)
from scripts.generate_apis_md import _escape_md_cell, _render_shape_cell, _shape


@dataclass(frozen=True)
class ModelDoc:
    name: str
    model: type[BaseModel]


def _schema_root_for(model: type[BaseModel]) -> tuple[dict[str, Any], dict[str, Any]]:
    schema = model.model_json_schema(ref_template="#/$defs/{model}")
    defs = dict(schema.get("$defs", {}))
    schema_title = str(schema.get("title") or model.__name__)
    root_schema = {k: v for k, v in schema.items() if k != "$defs"}
    defs[schema_title] = root_schema
    root = {"$defs": defs}
    entry_ref = {"$ref": f"#/$defs/{schema_title}"}
    return root, entry_ref


def _shape_for_model(model: type[BaseModel]) -> str:
    root, entry_ref = _schema_root_for(model)
    return _shape(entry_ref, root)


def _render_models_table(models: list[ModelDoc]) -> list[str]:
    lines = ["| Structure | Shape |", "| --- | --- |"]
    for item in models:
        model_cell = f"`{item.name}`"
        shape = _render_shape_cell(_shape_for_model(item.model), root={})
        lines.append(f"| {model_cell} | {_escape_md_cell(shape)} |")
    return lines


def generate_db_reference() -> str:
    global_models = [
        ModelDoc("PersistedGlobalState", PersistedGlobalState),
    ]
    session_models = [
        ModelDoc("PersistedSessionState", PersistedSessionState),
        ModelDoc("PersistedSessionMeta", PersistedSessionMeta),
    ]

    lines: list[str] = []
    lines.append("# DB Reference (Generated from Persisted Models)")
    lines.append("")
    lines.append("Generated from `daemon/persisted_models.py`.")
    lines.append("")
    lines.append("## Table of Contents")
    lines.append("- [Global State](#global-state)")
    lines.append("- [Session State](#session-state)")
    lines.append("")

    lines.append("## Global State")
    lines.extend(_render_models_table(global_models))
    lines.append("")

    lines.append("## Session State")
    lines.extend(_render_models_table(session_models))
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate DB markdown from daemon persisted models")
    parser.add_argument("--output", default="DB.generated.md")
    parser.add_argument("--stdout", action="store_true", help="Print markdown to stdout instead of writing file")
    args = parser.parse_args()

    content = generate_db_reference()
    if args.stdout:
        print(content, end="")
        return 0

    out_path = Path(args.output)
    out_path.write_text(content)
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
