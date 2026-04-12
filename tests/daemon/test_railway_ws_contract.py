"""Contract tests: docs/railway-ws.yaml <-> daemon WS handlers + Railway push_to_daemon calls.

Verifies that:
1. Every subscribe message in YAML has a daemon handler registered via register_handler().
2. Every daemon handler for a protocol message type has a YAML subscribe entry.
3. Every publish message in YAML appears in Railway's _DAEMON_MSG_HANDLERS (daemon -> Railway).
4. All subscribe/publish messages have non-empty x-feature.
5. All push_to_daemon() call sites use message types documented in YAML subscribe.
"""
import re
import yaml
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
DOCS_DIR = REPO_ROOT / "docs"
RAILWAY_WS_YAML = DOCS_DIR / "railway-ws.yaml"
DAEMON_MAIN = REPO_ROOT / "daemon" / "__main__.py"
DAEMON_PROTOCOL = REPO_ROOT / "railway" / "features" / "ws" / "daemon_protocol.py"
RAILWAY_WS_ROUTER = REPO_ROOT / "railway" / "features" / "ws" / "router.py"
RAILWAY_UPLOAD_ROUTER = REPO_ROOT / "railway" / "features" / "upload" / "router.py"


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _extract_channel_message_names(spec: dict, direction: str) -> set[str]:
    """Extract message type names from the given direction (subscribe or publish) in all channels."""
    names = set()
    for channel in spec.get("channels", {}).values():
        channel_dir = channel.get(direction, {})
        message = channel_dir.get("message", {})
        for ref in message.get("oneOf", []):
            ref_str = ref.get("$ref", "")
            if ref_str.startswith("#/components/messages/"):
                names.add(ref_str.split("/")[-1])
        # Handle single message (not oneOf)
        single_ref = message.get("$ref", "")
        if single_ref.startswith("#/components/messages/"):
            names.add(single_ref.split("/")[-1])
    return names


def _parse_daemon_register_handlers() -> set[str]:
    """Parse daemon/__main__.py for ws_client.register_handler("...", ...) calls."""
    text = DAEMON_MAIN.read_text()
    # Match: register_handler("msg_type", ...)
    matches = re.findall(r'register_handler\(\s*["\']([^"\']+)["\']', text)
    return set(matches)


def _parse_msg_constants(path: Path) -> dict[str, str]:
    """Parse MSG_X = "value" constants from daemon_protocol.py. Returns {constant_name: value}."""
    text = path.read_text()
    matches = re.findall(r'^(MSG_\w+)\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    return {name: value for name, value in matches}


def _parse_railway_daemon_msg_handler_keys() -> set[str]:
    """Parse _DAEMON_MSG_HANDLERS keys from railway router.py.

    These are message types received FROM the daemon (daemon -> Railway = publish direction).
    Keys can be MSG_* constants or literal strings.
    """
    text = RAILWAY_WS_ROUTER.read_text()
    msg_constants = _parse_msg_constants(DAEMON_PROTOCOL)

    # Find the _DAEMON_MSG_HANDLERS dict block
    handler_block_match = re.search(
        r'_DAEMON_MSG_HANDLERS\s*=\s*\{(.+?)\}',
        text,
        re.DOTALL,
    )
    if not handler_block_match:
        return set()

    block = handler_block_match.group(1)
    result = set()

    # Collect MSG_* constant references
    for const_name in re.findall(r'\b(MSG_\w+)\b', block):
        if const_name in msg_constants:
            result.add(msg_constants[const_name])

    # Collect literal string keys like "participant_registered"
    for literal in re.findall(r'["\']([a-z_]+)["\'](?=\s*:)', block):
        result.add(literal)

    return result


def _parse_push_to_daemon_types() -> set[str]:
    """Parse all message types sent via push_to_daemon() across railway code.

    These are Railway -> daemon messages (subscribe direction in YAML).
    We look for both:
    - push_to_daemon({"type": MSG_SOMETHING, ...})  — using MSG_* constants
    - push_to_daemon({"type": "literal_type", ...}) — using string literals
    Note: only covers push_to_daemon() calls. Direct websocket.send_json() calls for
    on-connect initialization (daemon_state_push, sync_files) are separately covered by
    test_subscribe_types_match_daemon_handlers via daemon register_handler() checks.
    """
    msg_constants = _parse_msg_constants(DAEMON_PROTOCOL)

    # Files that send messages to the daemon via push_to_daemon()
    source_files = [RAILWAY_WS_ROUTER, RAILWAY_UPLOAD_ROUTER]

    result = set()
    for fpath in source_files:
        text = fpath.read_text()

        # Match push_to_daemon({...}) with MSG_* constants
        for const_name in re.findall(r'push_to_daemon\s*\([^)]*?(MSG_\w+)', text):
            if const_name in msg_constants:
                result.add(msg_constants[const_name])

        # Match push_to_daemon({"type": "literal", ...}) patterns
        for m in re.finditer(
            r'push_to_daemon\s*\(\s*\{[^}]*?"type"\s*:\s*["\']([^"\']+)["\']',
            text,
            re.DOTALL,
        ):
            result.add(m.group(1))

    return result


class TestRailwayWsSubscribe:
    """Tests for subscribe channel (Railway -> daemon messages)."""

    def setup_method(self):
        assert RAILWAY_WS_YAML.exists(), f"Missing {RAILWAY_WS_YAML}"
        self.spec = _load_yaml(RAILWAY_WS_YAML)
        self.subscribe_names = _extract_channel_message_names(self.spec, "subscribe")

    def test_subscribe_types_match_daemon_handlers(self):
        """Every subscribe message in YAML must have a daemon handler registered.

        Exceptions:
        - pdf_download_complete: Railway sends it but daemon dropped the WS handler;
          daemon now polls via REST POST /api/slides/download-from-gdrive/{slug} instead.
          Kept in YAML for documentation completeness.
        """
        # Messages documented in YAML subscribe that no longer have active daemon handlers
        # (deprecated or migrated to REST polling)
        known_deprecated = {"pdf_download_complete"}

        daemon_handlers = _parse_daemon_register_handlers()
        yaml_subscribe = self.subscribe_names - known_deprecated

        missing_from_daemon = yaml_subscribe - daemon_handlers
        errors = []
        if missing_from_daemon:
            errors.append(
                "In YAML subscribe but NOT in daemon register_handler calls:\n"
                + "\n".join(f"  - {n}" for n in sorted(missing_from_daemon))
            )
        assert not errors, "\n".join(errors) + "\n\nAdd register_handler() in daemon/__main__.py or remove from YAML."

    def test_daemon_handlers_are_documented(self):
        """Every daemon handler for a protocol message type must appear in YAML subscribe."""
        msg_constants = _parse_msg_constants(DAEMON_PROTOCOL)
        protocol_types = set(msg_constants.values())
        daemon_handlers = _parse_daemon_register_handlers()

        # Only check handlers that correspond to known protocol constants (Railway -> daemon direction)
        # Determine which constants are Railway->daemon by checking they appear in subscribe
        # The subscribe protocol types are those in daemon register_handler that match MSG_ constants
        handlers_for_protocol_types = daemon_handlers & protocol_types

        yaml_subscribe = self.subscribe_names
        extra_in_daemon = handlers_for_protocol_types - yaml_subscribe

        errors = []
        if extra_in_daemon:
            errors.append(
                "Daemon handler registered but NOT in YAML subscribe:\n"
                + "\n".join(f"  + {n}" for n in sorted(extra_in_daemon))
            )
        assert not errors, "\n".join(errors) + "\n\nAdd message to YAML subscribe channel or remove handler."

    def test_all_subscribe_messages_have_x_feature(self):
        """All subscribe messages must have non-empty x-feature."""
        messages = self.spec.get("components", {}).get("messages", {})
        missing = []
        for msg_name in sorted(self.subscribe_names):
            if msg_name not in messages:
                continue
            feature = messages[msg_name].get("x-feature")
            if not isinstance(feature, str) or not feature.strip():
                missing.append(f"  - {msg_name}")
        assert not missing, (
            "Railway-WS subscribe messages missing x-feature:\n" + "\n".join(missing)
        )


class TestRailwayWsPublish:
    """Tests for publish channel (daemon -> Railway messages)."""

    def setup_method(self):
        assert RAILWAY_WS_YAML.exists(), f"Missing {RAILWAY_WS_YAML}"
        self.spec = _load_yaml(RAILWAY_WS_YAML)
        self.publish_names = _extract_channel_message_names(self.spec, "publish")

    def test_all_publish_messages_have_x_feature(self):
        """All publish messages must have non-empty x-feature."""
        messages = self.spec.get("components", {}).get("messages", {})
        missing = []
        for msg_name in sorted(self.publish_names):
            if msg_name not in messages:
                continue
            feature = messages[msg_name].get("x-feature")
            if not isinstance(feature, str) or not feature.strip():
                missing.append(f"  - {msg_name}")
        assert not missing, (
            "Railway-WS publish messages missing x-feature:\n" + "\n".join(missing)
        )

    def test_railway_daemon_handlers_are_documented(self):
        """All message types in Railway's _DAEMON_MSG_HANDLERS must appear in YAML publish.

        _DAEMON_MSG_HANDLERS processes messages received FROM the daemon (publish direction).
        """
        # Infrastructure / internal non-protocol types that are handled by Railway
        # but are not documented as standalone protocol messages in the YAML:
        # - participant_registered, participant_renamed, participant_avatar_updated,
        #   participant_location: daemon identity write-backs that piggyback on broadcast
        internal_only = {
            "participant_registered",
            "participant_renamed",
            "participant_avatar_updated",
            "participant_location",
        }

        handler_types = _parse_railway_daemon_msg_handler_keys() - internal_only
        yaml_publish = self.publish_names

        missing_from_yaml = handler_types - yaml_publish
        errors = []
        if missing_from_yaml:
            errors.append(
                "In Railway _DAEMON_MSG_HANDLERS but NOT in YAML publish:\n"
                + "\n".join(f"  - {n}" for n in sorted(missing_from_yaml))
            )
        assert not errors, "\n".join(errors) + "\n\nAdd message to YAML publish channel or add to internal_only set."

    def test_push_to_daemon_types_documented(self):
        """All message types sent via push_to_daemon() must appear in YAML subscribe.

        push_to_daemon() sends messages Railway -> daemon (subscribe direction).
        """
        push_types = _parse_push_to_daemon_types()
        yaml_subscribe = _extract_channel_message_names(self.spec, "subscribe")

        missing_from_yaml = push_types - yaml_subscribe
        errors = []
        if missing_from_yaml:
            errors.append(
                "Sent via push_to_daemon() but NOT in YAML subscribe:\n"
                + "\n".join(f"  - {n}" for n in sorted(missing_from_yaml))
            )
        assert not errors, "\n".join(errors) + "\n\nAdd message to YAML subscribe channel."
