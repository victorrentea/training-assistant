#!/usr/bin/env python3
"""Generate API Reference markdown from OpenAPI + AsyncAPI contracts.

Primary sources:
- docs/openapi.yaml
- docs/participant-ws.yaml
- docs/host-ws.yaml

Feature grouping source:
- REST: OpenAPI operation tags (with a small in-code split for tag 'misc')
- WS: daemon.ws_messages feature metadata maps
"""

from __future__ import annotations

import argparse
import copy
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

FEATURE_LABELS: dict[str, str] = {
    "session": "Session Management",
    "session_management": "Session Management",
    "slides": "Slides",
    "activity": "Activity Switching",
    "participant": "Identity",
    "identity": "Identity",
    "poll": "Poll",
    "wordcloud": "Word Cloud",
    "qa": "Q&A",
    "codereview": "Code Review",
    "debate": "Debate",
    "leaderboard": "Scores & Leaderboard",
    "scores_leaderboard": "Scores & Leaderboard",
    "emoji": "Emoji Reactions",
    "quiz": "Quiz Generation",
    "misc": "Misc",
    "paste_upload": "Paste & File Upload",
    "notes_summary": "Notes & Summary",
    "feedback": "Feedback",
    "reload": "Cross-cutting: Reload",
    "transcription": "Transcription",
    "host-state": "Identity",
    "_untagged": "Session Management",
}

FEATURE_ORDER = [
    "session_management",
    "identity",
    "slides",
    "activity",
    "poll",
    "wordcloud",
    "qa",
    "codereview",
    "debate",
    "scores_leaderboard",
    "emoji",
    "quiz",
    "paste_upload",
    "notes_summary",
    "feedback",
    "transcription",
    "reload",
    "misc",
]

HTTP_METHODS = {"get", "post", "put", "delete", "patch"}


@dataclass
class RestOp:
    method: str
    path: str
    title: str
    notes: list[str]
    request_shape: str
    response_shape: str


@dataclass
class WsMsg:
    name: str
    notes: list[str]
    payload_shape: str


@dataclass
class FeatureSection:
    participant_rest: list[RestOp]
    participant_ws: list[WsMsg]
    host_rest: list[RestOp]
    host_ws: list[WsMsg]


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def _resolve_ref(root: dict[str, Any], ref: str) -> dict[str, Any] | None:
    if not ref.startswith("#/"):
        return None
    node: Any = root
    for part in ref[2:].split("/"):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
        if node is None:
            return None
    if isinstance(node, dict):
        return node
    return None


def _schema_comment(schema: dict[str, Any] | Any) -> str:
    if not isinstance(schema, dict):
        return ""
    desc = schema.get("description")
    if isinstance(desc, str) and desc.strip():
        cleaned = " ".join(desc.strip().split())
        return cleaned
    return ""


def _collect_notes(spec: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    for key in ("summary", "description"):
        value = spec.get(key)
        if isinstance(value, str) and value.strip():
            notes.append(" ".join(value.strip().split()))
    extra = spec.get("x-doc-notes")
    if isinstance(extra, str) and extra.strip():
        notes.append(" ".join(extra.strip().split()))
    elif isinstance(extra, list):
        for item in extra:
            if isinstance(item, str) and item.strip():
                notes.append(" ".join(item.strip().split()))
    # preserve order, drop duplicates
    seen: set[str] = set()
    unique: list[str] = []
    for note in notes:
        if note in seen:
            continue
        seen.add(note)
        unique.append(note)
    return unique


def _collect_rest_doc(spec: dict[str, Any]) -> tuple[str, list[str]]:
    summary = spec.get("summary")
    summary_text = " ".join(summary.strip().split()) if isinstance(summary, str) and summary.strip() else ""
    notes = _collect_notes(spec)
    if summary_text:
        filtered = [note for note in notes if note != summary_text]
        return summary_text, filtered
    if notes:
        return notes[0], notes[1:]
    return "Endpoint", []


def _split_note_clauses(note: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", note.strip()) if part.strip()]


def _normalize_match_text(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return " ".join(cleaned.split())


def _verb_root(word: str) -> str:
    lowered = word.lower().strip()
    irregular = {
        "is": "be",
        "are": "be",
        "has": "have",
        "does": "do",
    }
    if lowered in irregular:
        return irregular[lowered]
    if lowered.endswith("ies") and len(lowered) > 3:
        return lowered[:-3] + "y"
    if lowered.endswith(("ches", "shes", "sses", "xes", "zes", "oes")) and len(lowered) > 4:
        return lowered[:-2]
    if lowered.endswith("s") and len(lowered) > 2:
        return lowered[:-1]
    return lowered


def _third_person_singular(verb: str) -> str:
    base = _verb_root(verb)
    if base == "be":
        return "is"
    if base == "have":
        return "has"
    if base == "do":
        return "does"
    if base.endswith("y") and len(base) > 1 and base[-2] not in "aeiou":
        return base[:-1] + "ies"
    if base.endswith(("s", "x", "z", "ch", "sh", "o")):
        return base + "es"
    return base + "s"


def _extract_action_parts(text: str) -> tuple[str, set[str]] | None:
    tokens = [token for token in re.findall(r"[A-Za-z0-9_]+", text.lower()) if token]
    if not tokens:
        return None
    idx = 0
    if tokens[idx] in {"host", "participant"}:
        idx += 1
    if idx >= len(tokens):
        return None
    verb = _verb_root(tokens[idx])
    object_tokens = {token for token in tokens[idx + 1 :] if token not in {"a", "an", "the"}}
    return verb, object_tokens


def _is_redundant_clause(clause: str, title: str) -> bool:
    title_norm = _normalize_match_text(title)
    clause_norm = _normalize_match_text(clause)
    if not title_norm or not clause_norm:
        return False
    if clause_norm == title_norm:
        return True
    if clause_norm.startswith(f"{title_norm} "):
        return True
    if clause_norm.startswith(f"host {title_norm} "):
        return True
    if clause_norm.startswith(f"participant {title_norm} "):
        return True
    title_action = _extract_action_parts(title)
    clause_action = _extract_action_parts(clause)
    if title_action and clause_action:
        title_verb, title_objects = title_action
        clause_verb, clause_objects = clause_action
        if title_verb == clause_verb and title_objects and title_objects.issubset(clause_objects):
            return True
    return False


def _rewrite_actor_action(title: str, note: str) -> str | None:
    match = re.match(r"^(Host|Participant)\s+([A-Za-z_]+)\s+(.+?)[.!?]?$", note.strip())
    if not match:
        return None
    actor, note_verb, note_object = match.groups()
    title_words = [w for w in re.findall(r"[A-Za-z0-9_]+", title) if w]
    if title_words and title_words[0].lower() in {"host", "participant"}:
        title_words = title_words[1:]
    if len(title_words) < 2:
        return None
    title_verb = _verb_root(title_words[0])
    note_verb_root = _verb_root(note_verb)
    synonyms: dict[str, set[str]] = {
        "set": {"switch", "change", "update"},
    }
    allowed = {title_verb, *synonyms.get(title_verb, set())}
    if note_verb_root not in allowed:
        return None

    object_text = note_object.strip().rstrip(" .")
    if not object_text:
        return None
    return f"{actor} {_third_person_singular(title_verb)} {object_text}."


def _merge_title_with_details(title: str, details: list[str]) -> str:
    cleaned_details: list[str] = []
    for detail in details:
        text = detail.strip().rstrip(".")
        if not text:
            continue
        if text and text[:1].isalpha() and len(text) > 1 and text[:2].isupper():
            cleaned = text
        else:
            cleaned = text[0].lower() + text[1:] if text else text
        cleaned_details.append(cleaned)
    if not cleaned_details:
        return title
    return f"{title}, {'; '.join(cleaned_details)}."


def _compose_rest_endpoint_text(op: RestOp) -> str:
    details: list[str] = []
    actor_rewrite: str | None = None
    if op.notes:
        actor_rewrite = _rewrite_actor_action(op.title, op.notes[0])

    for idx, note in enumerate(op.notes):
        if idx == 0 and actor_rewrite:
            continue
        for clause in _split_note_clauses(note):
            if _is_redundant_clause(clause, op.title):
                continue
            details.append(clause)

    if actor_rewrite:
        if not details:
            return actor_rewrite
        details_text = " ".join(detail.strip() for detail in details if detail.strip())
        if not details_text:
            return actor_rewrite
        return f"{actor_rewrite} {details_text}"

    return _merge_title_with_details(op.title, details)


def _shape(
    schema: dict[str, Any] | bool | Any | None,
    root: dict[str, Any],
    depth: int = 0,
    top_level: bool = True,
) -> str:
    if schema is True:
        return "any"
    if schema is False:
        return "never"
    if not schema:
        return "any"
    if not isinstance(schema, dict):
        return "any"

    if "$ref" in schema:
        ref = str(schema["$ref"])
        ref_name = ref.split("/")[-1]
        resolved = _resolve_ref(root, ref)
        if resolved is None:
            return ref_name
        if depth > 0:
            return ref_name
        return _shape(resolved, root, depth + 1, top_level=top_level)

    if "oneOf" in schema:
        return " | ".join(_shape(s, root, depth + 1, top_level=False) for s in schema.get("oneOf", []))
    if "anyOf" in schema:
        return " | ".join(_shape(s, root, depth + 1, top_level=False) for s in schema.get("anyOf", []))
    if "allOf" in schema:
        return " & ".join(_shape(s, root, depth + 1, top_level=False) for s in schema.get("allOf", []))

    typ = schema.get("type")

    if isinstance(schema.get("enum"), list):
        enum_vals = ["null" if v is None else repr(v) for v in schema["enum"]]
        base = " | ".join(enum_vals)
    elif typ == "null":
        base = "null"
    elif typ == "string":
        base = "string"
    elif typ == "integer":
        base = "int"
    elif typ == "number":
        base = "number"
    elif typ == "boolean":
        base = "bool"
    elif typ == "array":
        base = f"list[{_shape(schema.get('items', {}), root, depth + 1, top_level=False)}]"
    elif typ == "object" or "properties" in schema or "additionalProperties" in schema:
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        if isinstance(props, dict) and props:
            if depth >= 2:
                base = "object"
            else:
                fields: list[str] = []
                for name, child in props.items():
                    if not isinstance(child, dict):
                        continue
                    optional = "" if name in required else "?"
                    child_type = _shape(child, root, depth + 1, top_level=False)
                    comment = _schema_comment(child)
                    line = f"{name}{optional}: {child_type}"
                    if comment:
                        line += f"  # {comment}"
                    fields.append(line)
                if top_level and len(fields) >= 2:
                    base = "\n".join(fields)
                else:
                    base = "{" + ", ".join(fields) + "}"
        elif "additionalProperties" in schema:
            base = f"dict[str, {_shape(schema.get('additionalProperties', {}), root, depth + 1, top_level=False)}]"
        else:
            base = "dict"
    else:
        base = "any"

    if schema.get("nullable"):
        base = f"{base} | null"
    return base


def _rest_request_shape(op: dict[str, Any], openapi: dict[str, Any]) -> str:
    body = op.get("requestBody")
    if not isinstance(body, dict):
        return "-"
    content = body.get("content", {})
    if not isinstance(content, dict) or not content:
        return "-"

    parts: list[str] = []
    for spec in content.values():
        schema = spec.get("schema", {}) if isinstance(spec, dict) else {}
        shape = _shape(schema, openapi)
        if shape not in parts:
            parts.append(shape)
    if not parts:
        return "-"
    if len(parts) == 1:
        return parts[0]
    return " | ".join(parts)


def _rest_response_shape(op: dict[str, Any], openapi: dict[str, Any]) -> str:
    responses = op.get("responses", {})
    if not isinstance(responses, dict) or not responses:
        return "unknown"

    status = None
    for code in ("200", "201", "202", "204"):
        if code in responses:
            status = code
            break
    if status is None:
        status = sorted(responses.keys())[0]

    resp = responses.get(status, {})
    if not isinstance(resp, dict):
        return "unknown"
    if status == "204":
        return "-"

    content = resp.get("content", {})
    if not isinstance(content, dict) or not content:
        desc = resp.get("description")
        if isinstance(desc, str) and desc.strip() and desc.strip().lower() not in {"successful response", "no content"}:
            return desc.strip()
        return "-"

    if "application/json" in content:
        schema = content["application/json"].get("schema", {}) if isinstance(content["application/json"], dict) else {}
        return _shape(schema, openapi)

    ctype = sorted(content.keys())[0]
    schema = content[ctype].get("schema", {}) if isinstance(content[ctype], dict) else {}
    return f"{ctype}: {_shape(schema, openapi)}"


def _feature_for_misc_path(path: str) -> str:
    if "paste" in path or "upload" in path:
        return "paste_upload"
    if "feedback" in path:
        return "feedback"
    if "/notes" in path or "/summary" in path:
        return "notes_summary"
    if "slides-cache-status" in path:
        return "slides"
    if "transcription-language" in path:
        return "transcription"
    if "/mode" in path:
        return "session_management"
    return "misc"


def _normalize_rest_feature(tag: str, path: str) -> str:
    tag = tag or "_untagged"
    if tag == "_untagged":
        return "session_management"
    if tag == "session":
        return "session_management"
    if tag == "participant":
        return "identity"
    if tag == "host-state":
        return "identity"
    if tag == "leaderboard":
        return "scores_leaderboard"
    if tag == "misc":
        return _feature_for_misc_path(path)
    return tag


def _audience_for_path(path: str) -> str:
    if "/api/participant/" in path:
        return "participant"
    return "host"


def _extract_rest(openapi: dict[str, Any], sections: dict[str, FeatureSection]) -> None:
    for path, methods in sorted(openapi.get("paths", {}).items()):
        if not isinstance(methods, dict):
            continue
        for method, op in sorted(methods.items()):
            if method.lower() not in HTTP_METHODS:
                continue
            if not isinstance(op, dict):
                continue

            tags = op.get("tags") or ["_untagged"]
            tag = str(tags[0])
            feature = str(op.get("x-feature") or _normalize_rest_feature(tag, path))
            section = sections.setdefault(feature, FeatureSection([], [], [], []))

            title, notes = _collect_rest_doc(op)
            rest = RestOp(
                method=method.upper(),
                path=path,
                title=title,
                notes=notes,
                request_shape=_rest_request_shape(op, openapi),
                response_shape=_rest_response_shape(op, openapi),
            )

            audience = _audience_for_path(path)
            if audience == "participant":
                section.participant_rest.append(rest)
            else:
                section.host_rest.append(rest)


def _extract_ws(
    spec: dict[str, Any],
    sections: dict[str, FeatureSection],
    audience: str,
) -> None:
    components = spec.get("components", {})
    messages = components.get("messages", {})

    for channel in spec.get("channels", {}).values():
        if not isinstance(channel, dict):
            continue
        subscribe = channel.get("subscribe", {})
        message = subscribe.get("message", {})
        one_of = message.get("oneOf", [])
        for ref in one_of:
            if not isinstance(ref, dict):
                continue
            ref_str = str(ref.get("$ref", ""))
            if not ref_str.startswith("#/components/messages/"):
                continue
            msg_name = ref_str.split("/")[-1]
            msg_spec = messages.get(msg_name, {})
            if not isinstance(msg_spec, dict):
                continue

            feature = str(msg_spec.get("x-feature") or "misc")
            section = sections.setdefault(feature, FeatureSection([], [], [], []))
            payload = msg_spec.get("payload", {})
            ws = WsMsg(
                name=msg_name,
                notes=_collect_notes(msg_spec),
                payload_shape=_ws_payload_shape(payload if isinstance(payload, dict) else {}, spec),
            )
            if audience == "participant":
                section.participant_ws.append(ws)
            else:
                section.host_ws.append(ws)


def _feature_title(feature_id: str) -> str:
    return FEATURE_LABELS.get(feature_id, feature_id.replace("_", " ").title())


def _escape_md_cell(value: str) -> str:
    return value.replace("|", "\\|")


def _render_shape_cell(shape: str) -> str:
    if shape.strip() in {"", "-", "none"}:
        return "-"
    if "\n" in shape:
        lines = [line.strip() for line in shape.splitlines() if line.strip()]
        return "<br>".join(f"`{line}`" for line in lines)
    return f"`{shape}`"


def _render_rest(items: list[RestOp]) -> list[str]:
    lines: list[str] = ["| Endpoint | Request | Response |", "| --- | --- | --- |"]
    for op in sorted(items, key=lambda i: (i.path, i.method)):
        endpoint_parts = [_compose_rest_endpoint_text(op), f"`{op.method} {op.path}`"]
        endpoint = _escape_md_cell("<br>".join(endpoint_parts))
        request = _escape_md_cell(_render_shape_cell(op.request_shape))
        response = _escape_md_cell(_render_shape_cell(op.response_shape))
        lines.append(f"| {endpoint} | {request} | {response} |")
    return lines


def _normalize_ws_token(token: str) -> str:
    base = token.lower().strip()
    synonyms = {
        "changed": "updated",
        "change": "updated",
        "updates": "updated",
        "update": "updated",
        "opens": "opened",
        "open": "opened",
        "closes": "closed",
        "close": "closed",
        "sets": "set",
    }
    return synonyms.get(base, base)


def _ws_keywords_from_name(message_name: str) -> set[str]:
    return {
        _normalize_ws_token(token)
        for token in message_name.lower().split("_")
        if token and token not in {"msg", "message"}
    }


def _ws_keywords_from_note(note: str) -> set[str]:
    stopwords = {
        "a",
        "an",
        "the",
        "for",
        "of",
        "and",
        "or",
        "by",
        "to",
        "in",
        "on",
        "from",
        "with",
        "host",
        "participant",
        "participants",
        "current",
        "type",
        "client",
        "browser",
        "daemon",
        "received",
    }
    words = re.findall(r"[a-z0-9_]+", note.lower())
    return {
        _normalize_ws_token(word)
        for word in words
        if word and word not in stopwords
    }


def _is_redundant_ws_note(note: str, message_name: str) -> bool:
    note_keywords = _ws_keywords_from_note(note)
    if not note_keywords:
        return True
    name_keywords = _ws_keywords_from_name(message_name)
    return bool(name_keywords) and note_keywords.issubset(name_keywords)


def _render_ws(items: list[WsMsg]) -> list[str]:
    lines: list[str] = ["| Message | Payload |", "| --- | --- |"]
    for msg in items:
        filtered_notes = [note for note in msg.notes if not _is_redundant_ws_note(note, msg.name)]
        message_parts = [*filtered_notes, f"`{msg.name}`"]
        message = _escape_md_cell("<br>".join(message_parts))
        payload = _render_shape_cell(msg.payload_shape)
        lines.append(f"| {message} | {_escape_md_cell(payload)} |")
    return lines


def _ws_payload_shape(payload: dict[str, Any], root: dict[str, Any]) -> str:
    schema = payload
    if "$ref" in schema:
        resolved = _resolve_ref(root, str(schema["$ref"]))
        if isinstance(resolved, dict):
            schema = resolved

    if isinstance(schema, dict):
        props = schema.get("properties")
        if isinstance(props, dict) and "type" in props:
            stripped = copy.deepcopy(schema)
            stripped_props = stripped.get("properties", {})
            if isinstance(stripped_props, dict):
                stripped_props.pop("type", None)
                stripped["properties"] = stripped_props
            required = stripped.get("required")
            if isinstance(required, list):
                stripped["required"] = [field for field in required if field != "type"]
            if isinstance(stripped.get("properties"), dict) and not stripped["properties"] and "additionalProperties" not in stripped:
                return "-"
            return _shape(stripped, root)

    return _shape(schema, root)


def generate_api_reference(
    openapi_path: Path,
    participant_ws_path: Path,
    host_ws_path: Path,
) -> str:
    openapi = _load_yaml(openapi_path)
    participant_ws = _load_yaml(participant_ws_path)
    host_ws = _load_yaml(host_ws_path)

    sections: dict[str, FeatureSection] = {}

    _extract_rest(openapi, sections)
    _extract_ws(participant_ws, sections, "participant")
    _extract_ws(host_ws, sections, "host")

    feature_ids = [f for f in FEATURE_ORDER if f in sections]
    feature_ids.extend(sorted(f for f in sections.keys() if f not in feature_ids))

    lines: list[str] = []
    lines.append("# API Reference (Generated from Contracts)")
    lines.append("")
    lines.append("Generated from `docs/openapi.yaml`, `docs/participant-ws.yaml`, and `docs/host-ws.yaml`.")
    lines.append("")

    lines.append("## Table of Contents")
    for feature_id in feature_ids:
        title = _feature_title(feature_id)
        anchor = "feature-" + title.lower().replace("&", "").replace(":", "").replace(" ", "-")
        lines.append(f"- [{title}](#{anchor})")
    lines.append("")

    for feature_id in feature_ids:
        title = _feature_title(feature_id)
        section = sections[feature_id]
        subsections: list[tuple[str, list[str]]] = []
        if section.participant_rest:
            subsections.append(("Participant REST", _render_rest(section.participant_rest)))
        if section.participant_ws:
            subsections.append(("Participant WS", _render_ws(section.participant_ws)))
        if section.host_rest:
            subsections.append(("Host REST", _render_rest(section.host_rest)))
        if section.host_ws:
            subsections.append(("Host WS", _render_ws(section.host_ws)))

        if not subsections:
            continue

        lines.append(f"## Feature: {title}")
        lines.append("")
        for subsection_title, subsection_lines in subsections:
            lines.append(f"### {subsection_title}")
            lines.extend(subsection_lines)
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate API markdown from API contracts")
    parser.add_argument("--openapi", default="docs/openapi.yaml")
    parser.add_argument("--participant-ws", default="docs/participant-ws.yaml")
    parser.add_argument("--host-ws", default="docs/host-ws.yaml")
    parser.add_argument("--output", default="API.generated.md")
    parser.add_argument("--stdout", action="store_true", help="Print markdown to stdout instead of writing file")
    args = parser.parse_args()

    content = generate_api_reference(
        Path(args.openapi),
        Path(args.participant_ws),
        Path(args.host_ws),
    )

    if args.stdout:
        print(content, end="")
        return 0

    out_path = Path(args.output)
    out_path.write_text(content)
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
