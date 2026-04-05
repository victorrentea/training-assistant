"""Contract tests: Pydantic WS message models (daemon/ws_messages.py) vs AsyncAPI YAML specs.

Verifies that:
1. Every message type defined in the YAML channel is present in the registry (and vice versa).
2. Every field in each YAML message payload is present in the corresponding Pydantic model
   (and vice versa).

Meta messages ('state', 'kicked') are intentionally excluded from the registries because
they are not incremental broadcast events.
"""
import pytest
import yaml
from pathlib import Path

from daemon.ws_messages import PARTICIPANT_MESSAGES, HOST_MESSAGES

DOCS_DIR = Path(__file__).parent.parent.parent / "docs"
PARTICIPANT_YAML = DOCS_DIR / "participant-ws.yaml"
HOST_YAML = DOCS_DIR / "host-ws.yaml"


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _extract_message_names(spec: dict) -> set[str]:
    """Extract message type names from AsyncAPI spec channels (oneOf $ref list)."""
    names = set()
    for channel in spec.get("channels", {}).values():
        subscribe = channel.get("subscribe", {})
        message = subscribe.get("message", {})
        for ref in message.get("oneOf", []):
            # ref looks like: {"$ref": "#/components/messages/scores_updated"}
            ref_str = ref.get("$ref", "")
            if ref_str.startswith("#/components/messages/"):
                names.add(ref_str.split("/")[-1])
    return names


def _extract_message_fields(spec: dict, msg_name: str) -> set[str]:
    """Extract field names from a message's payload properties in the AsyncAPI spec."""
    msg = spec.get("components", {}).get("messages", {}).get(msg_name, {})
    payload = msg.get("payload", {})
    props = payload.get("properties", {})
    # Exclude 'type' field — it's the discriminator, present in every model
    return {k for k in props.keys() if k != "type"}


class TestParticipantWsContract:
    @pytest.fixture(scope="class")
    def spec(self):
        assert PARTICIPANT_YAML.exists(), f"Missing {PARTICIPANT_YAML}"
        return _load_yaml(PARTICIPANT_YAML)

    def test_message_types_match(self, spec):
        """Every message in the registry must exist in YAML, and vice versa."""
        yaml_names = _extract_message_names(spec)
        registry_names = set(PARTICIPANT_MESSAGES.keys())

        # Filter to only messages that have a components/messages definition
        yaml_defined = {n for n in yaml_names if n in spec.get("components", {}).get("messages", {})}

        # 'state' is a full-state message sent on connect/reconnect — not an incremental event
        meta_messages = {"state"}
        yaml_defined -= meta_messages

        missing_from_registry = yaml_defined - registry_names
        extra_in_registry = registry_names - yaml_defined

        errors = []
        if missing_from_registry:
            errors.append(
                "In YAML but NOT in PARTICIPANT_MESSAGES registry:\n"
                + "\n".join(f"  - {n}" for n in sorted(missing_from_registry))
            )
        if extra_in_registry:
            errors.append(
                "In PARTICIPANT_MESSAGES registry but NOT in YAML:\n"
                + "\n".join(f"  + {n}" for n in sorted(extra_in_registry))
            )

        assert not errors, "\n".join(errors) + "\n\nUpdate YAML or registry to match."

    def test_message_fields_match(self, spec):
        """Field names in each Pydantic model must match the YAML payload properties."""
        yaml_names = _extract_message_names(spec)
        errors = []

        for msg_name, model_cls in sorted(PARTICIPANT_MESSAGES.items()):
            if msg_name not in yaml_names:
                continue  # type mismatch caught by test_message_types_match

            yaml_fields = _extract_message_fields(spec, msg_name)
            # Get Pydantic model fields, excluding 'type'
            model_fields = {k for k in model_cls.model_fields.keys() if k != "type"}

            missing = yaml_fields - model_fields
            extra = model_fields - yaml_fields

            if missing:
                errors.append(f"  {msg_name}: fields in YAML but not in model: {sorted(missing)}")
            if extra:
                errors.append(f"  {msg_name}: fields in model but not in YAML: {sorted(extra)}")

        assert not errors, "Field mismatches:\n" + "\n".join(errors)


class TestHostWsContract:
    @pytest.fixture(scope="class")
    def spec(self):
        assert HOST_YAML.exists(), f"Missing {HOST_YAML}"
        return _load_yaml(HOST_YAML)

    def test_message_types_match(self, spec):
        """Every message in the registry must exist in YAML, and vice versa."""
        yaml_names = _extract_message_names(spec)
        registry_names = set(HOST_MESSAGES.keys())

        yaml_defined = {n for n in yaml_names if n in spec.get("components", {}).get("messages", {})}

        # 'state' is full-state on connect; 'kicked' is a one-way eviction signal — neither is a registry event
        meta_messages = {"state", "kicked"}
        yaml_defined -= meta_messages

        missing_from_registry = yaml_defined - registry_names
        extra_in_registry = registry_names - yaml_defined

        errors = []
        if missing_from_registry:
            errors.append(
                "In YAML but NOT in HOST_MESSAGES registry:\n"
                + "\n".join(f"  - {n}" for n in sorted(missing_from_registry))
            )
        if extra_in_registry:
            errors.append(
                "In HOST_MESSAGES registry but NOT in YAML:\n"
                + "\n".join(f"  + {n}" for n in sorted(extra_in_registry))
            )

        assert not errors, "\n".join(errors) + "\n\nUpdate YAML or registry to match."

    def test_message_fields_match(self, spec):
        """Field names in each Pydantic model must match the YAML payload properties."""
        yaml_names = _extract_message_names(spec)
        errors = []

        for msg_name, model_cls in sorted(HOST_MESSAGES.items()):
            if msg_name not in yaml_names:
                continue  # type mismatch caught by test_message_types_match

            yaml_fields = _extract_message_fields(spec, msg_name)
            model_fields = {k for k in model_cls.model_fields.keys() if k != "type"}

            missing = yaml_fields - model_fields
            extra = model_fields - yaml_fields

            if missing:
                errors.append(f"  {msg_name}: fields in YAML but not in model: {sorted(missing)}")
            if extra:
                errors.append(f"  {msg_name}: fields in model but not in YAML: {sorted(extra)}")

        assert not errors, "Field mismatches:\n" + "\n".join(errors)
