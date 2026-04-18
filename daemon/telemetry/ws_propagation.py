"""Inject/extract W3C trace context into/from WS message dicts.

Convention: trace context is carried in the `_traceparent` field
(underscore-prefixed) of JSON message payloads. This field is ignored
by all existing message handlers.
"""
from opentelemetry import propagate
from opentelemetry.propagators.textmap import Getter, Setter

_FIELD = "_traceparent"


class _DictSetter(Setter[dict]):  # type: ignore[type-arg]
    def set(self, carrier: dict, key: str, value: str) -> None:
        if key == "traceparent":
            carrier[_FIELD] = value


class _DictGetter(Getter[dict]):  # type: ignore[type-arg]
    def get(self, carrier: dict, key: str) -> list[str]:
        if key == "traceparent":
            val = carrier.get(_FIELD)
            return [val] if val else []
        return []

    def keys(self, carrier: dict) -> list[str]:
        return [_FIELD] if _FIELD in carrier else []


_setter = _DictSetter()
_getter = _DictGetter()


def inject_trace_context(msg: dict) -> None:
    """Inject the current span's trace context into a WS message dict."""
    propagate.inject(msg, setter=_setter)


def extract_trace_context(msg: dict):
    """Extract trace context from a WS message dict. Returns a Context or None."""
    if _FIELD not in msg:
        return None
    return propagate.extract(msg, getter=_getter)
