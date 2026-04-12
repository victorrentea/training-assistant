"""Inject/extract W3C trace context into/from WS message dicts.

Convention: trace context is carried in the `_traceparent` field
(underscore-prefixed) of JSON message payloads. This field is ignored
by all existing message handlers.
"""
from opentelemetry import propagate

_FIELD = "_traceparent"


class _DictSetter:
    def set(self, carrier, key, value):
        if key == "traceparent":
            carrier[_FIELD] = value


class _DictGetter:
    def get(self, carrier, key):
        if key == "traceparent":
            val = carrier.get(_FIELD)
            return [val] if val else []
        return []

    def keys(self, carrier):
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
