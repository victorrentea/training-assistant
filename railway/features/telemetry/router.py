"""Receive browser OTel spans and append to the shared traces file."""
import json
import os
import threading

from fastapi import APIRouter, Request
from fastapi.responses import Response

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])

_traces_file = os.environ.get("OTEL_TRACES_FILE")
_lock = threading.Lock()


@router.post("/spans", status_code=204)
async def receive_spans(request: Request):
    """Receive browser spans as JSON array and append to traces file."""
    if not _traces_file:
        return Response(status_code=204)
    body = await request.body()
    try:
        spans = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return Response(status_code=400)
    if not isinstance(spans, list):
        return Response(status_code=400)
    with _lock:
        with open(_traces_file, "a", encoding="utf-8") as f:
            for span in spans:
                f.write(json.dumps(span) + "\n")
    return Response(status_code=204)
