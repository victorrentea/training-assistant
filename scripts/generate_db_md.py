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
from scripts.generate_apis_md import _render_shape_cell, _shape


@dataclass(frozen=True)
class ModelDoc:
    name: str
    model: type[BaseModel]


def _schema_root_for(model: type[BaseModel]) -> tuple[dict[str, Any], dict[str, Any]]:
    schema = model.model_json_schema(ref_template="#/$defs/{model}")
    defs = dict(schema.get("$defs", {}))
    schema_title = str(schema.get("title") or model.__name__)
    root_schema = {k: v for k, v in schema.items() if k != "$defs"}

    # Keep DB docs focused on serialized shape: hide fields marked exclude=True.
    excluded = {name for name, field in model.model_fields.items() if field.exclude is True}
    if excluded:
        properties = root_schema.get("properties")
        if isinstance(properties, dict):
            for field_name in excluded:
                properties.pop(field_name, None)
        required = root_schema.get("required")
        if isinstance(required, list):
            root_schema["required"] = [name for name in required if name not in excluded]

    defs[schema_title] = root_schema
    root = {"$defs": defs}
    entry_ref = {"$ref": f"#/$defs/{schema_title}"}
    return root, entry_ref


def _shape_for_model(model: type[BaseModel]) -> str:
    root, entry_ref = _schema_root_for(model)
    return _shape(entry_ref, root)


def _shape_lines_for_model(model: type[BaseModel]) -> list[str]:
    shape = _render_shape_cell(_shape_for_model(model), root={})
    pieces = [piece for piece in shape.split("<br>") if piece]
    return [piece.replace("&nbsp;", " ").strip() for piece in pieces]


def _render_models(models: list[ModelDoc]) -> list[str]:
    lines: list[str] = []
    for item in models:
        lines.append(f"### `{item.name}`")
        lines.append("")
        for row in _shape_lines_for_model(item.model):
            lines.append(f"- {row}")
        lines.append("")
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
    lines.extend(_render_models(global_models))

    lines.append("## Session State")
    lines.extend(_render_models(session_models))

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
