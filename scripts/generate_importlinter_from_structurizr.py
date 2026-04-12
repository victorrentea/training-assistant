"""Generate Import Linter contracts from Structurizr DSL relationships.

This focuses on Railway feature packages and turns component dependencies
declared in `docs/c4model.dsl` into forbidden-import contracts.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE = PROJECT_ROOT / "docs" / "c4model.dsl"
DEFAULT_OUTPUT = PROJECT_ROOT / "docs" / "c4views" / "importlinter.ini"
DEFAULT_REPORT = PROJECT_ROOT / "docs" / "c4views" / "importlinter-report.json"

COMPONENT_RE = re.compile(
    r'^\s*(?P<id>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*component\s+"[^"]+"\s+"[^"]*"\s+"(?P<code>[^"]+)"\s*$'
)
REL_RE = re.compile(r"^\s*(?P<src>[A-Za-z_][A-Za-z0-9_]*)\s*->\s*(?P<dst>[A-Za-z_][A-Za-z0-9_]*)\b")


@dataclass(frozen=True)
class Component:
    component_id: str
    code_path: str
    module: str | None
    exists: bool


def _path_to_module(code_path: str) -> str | None:
    raw = code_path.strip()
    normalized = raw
    if normalized.endswith("/*"):
        normalized = normalized[:-2]
    elif normalized.endswith(".py"):
        normalized = normalized[:-3]

    normalized = normalized.replace("\\", "/")

    if normalized.startswith("features/"):
        normalized = f"railway/{normalized}"
    elif normalized.startswith("shared/"):
        normalized = f"railway/{normalized}"

    if "/" in normalized:
        normalized = normalized.strip("/").replace("/", ".")

    if normalized.startswith(("railway.", "daemon.")):
        return normalized
    return None


def _module_exists(module: str) -> bool:
    module_path = PROJECT_ROOT / module.replace(".", "/")
    if (module_path / "__init__.py").exists():
        return True
    if module_path.with_suffix(".py").exists():
        return True
    return False


def _parse_workspace(workspace_text: str) -> tuple[dict[str, Component], list[tuple[str, str]]]:
    components: dict[str, Component] = {}
    relationships: list[tuple[str, str]] = []

    for line in workspace_text.splitlines():
        comp_match = COMPONENT_RE.match(line)
        if comp_match:
            component_id = comp_match.group("id")
            code_path = comp_match.group("code")
            module = _path_to_module(code_path)
            exists = bool(module and _module_exists(module))
            components[component_id] = Component(
                component_id=component_id,
                code_path=code_path,
                module=module,
                exists=exists,
            )
            continue

        rel_match = REL_RE.match(line)
        if rel_match:
            relationships.append((rel_match.group("src"), rel_match.group("dst")))

    return components, relationships


def _render_contract_key(source: str, target: str) -> str:
    key = f"{source}__not__{target}"
    return re.sub(r"[^a-zA-Z0-9_]+", "_", key)


def build_importlinter_config(
    components: dict[str, Component],
    relationships: list[tuple[str, str]],
) -> tuple[str, dict[str, object]]:
    resolved_components: list[dict[str, str]] = []
    unresolved_components: list[dict[str, str]] = []

    railway_modules_by_id: dict[str, str] = {}
    for component in components.values():
        if component.module and component.module.startswith(("railway.features.", "railway.shared")):
            if component.exists:
                railway_modules_by_id[component.component_id] = component.module
                resolved_components.append(
                    {
                        "id": component.component_id,
                        "code_path": component.code_path,
                        "module": component.module,
                    }
                )
            else:
                unresolved_components.append(
                    {
                        "id": component.component_id,
                        "code_path": component.code_path,
                        "module": component.module,
                        "reason": "module_not_found",
                    }
                )
        elif component.module is None:
            unresolved_components.append(
                {
                    "id": component.component_id,
                    "code_path": component.code_path,
                    "reason": "unsupported_code_path",
                }
            )

    feature_modules = sorted(
        {
            module
            for module in railway_modules_by_id.values()
            if module.startswith("railway.features.")
        }
    )

    allowed_targets: dict[str, set[str]] = {module: {module} for module in feature_modules}
    for module in feature_modules:
        allowed_targets[module].add("railway.shared")

    dsl_edges_used: list[dict[str, str]] = []
    for src_id, dst_id in relationships:
        src_module = railway_modules_by_id.get(src_id)
        dst_module = railway_modules_by_id.get(dst_id)
        if not src_module or not dst_module:
            continue
        if not src_module.startswith("railway.features."):
            continue
        if not (dst_module.startswith("railway.features.") or dst_module.startswith("railway.shared")):
            continue
        allowed_targets[src_module].add(dst_module)
        dsl_edges_used.append(
            {
                "source_component": src_id,
                "target_component": dst_id,
                "source_module": src_module,
                "target_module": dst_module,
            }
        )

    lines: list[str] = []
    lines.append("# Generated from docs/c4model.dsl")
    lines.append("# Do not edit by hand. Regenerate via scripts/generate_importlinter_from_structurizr.py")
    lines.append("")
    lines.append("[importlinter]")
    lines.append("root_package = railway")
    lines.append("")

    contract_count = 0
    generated_contracts: list[dict[str, str]] = []
    for source_module in feature_modules:
        for target_module in feature_modules:
            if source_module == target_module:
                continue
            if target_module in allowed_targets[source_module]:
                continue

            key = _render_contract_key(source_module, target_module)
            lines.append(f"[importlinter:contract:{key}]")
            lines.append(f"name = {source_module} must not import {target_module}")
            lines.append("type = forbidden")
            lines.append("source_modules =")
            lines.append(f"    {source_module}")
            lines.append("forbidden_modules =")
            lines.append(f"    {target_module}")
            lines.append("")
            contract_count += 1
            generated_contracts.append(
                {
                    "source_module": source_module,
                    "target_module": target_module,
                    "type": "forbidden",
                }
            )

    report: dict[str, object] = {
        "resolved_components": sorted(resolved_components, key=lambda x: x["id"]),
        "unresolved_components": sorted(unresolved_components, key=lambda x: x["id"]),
        "dsl_relationships_used": dsl_edges_used,
        "generated_contracts": generated_contracts,
        "generated_contract_count": contract_count,
    }
    return "\n".join(lines).rstrip() + "\n", report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate Import Linter config from Structurizr DSL component relationships."
    )
    parser.add_argument("--workspace", default=str(DEFAULT_WORKSPACE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()

    workspace_path = Path(args.workspace)
    workspace_text = workspace_path.read_text(encoding="utf-8")
    components, relationships = _parse_workspace(workspace_text)
    config_content, report = build_importlinter_config(components, relationships)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(config_content, encoding="utf-8")
    print(f"Wrote {output_path}")

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {report_path}")

    if args.stdout:
        print(config_content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
