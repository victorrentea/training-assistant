from dataclasses import dataclass, field
from typing import Optional
import anthropic
import time
from daemon import log

# Pricing per 1M tokens (USD)
PRICING = {
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
}


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0

    def add(self, input_tokens: int, output_tokens: int, model: str = "") -> float:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        # Compute cost using model-specific pricing
        pricing = PRICING.get(model, PRICING["claude-sonnet-4-6"])
        cost = (
            input_tokens * pricing["input"] + output_tokens * pricing["output"]
        ) / 1_000_000
        self.estimated_cost_usd += cost
        return cost

    def to_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 4),
        }


# Singleton accumulator
_usage = TokenUsage()


def get_usage() -> TokenUsage:
    return _usage


def _real_create_message(
    api_key: str,
    model: str,
    max_tokens: int,
    messages: list,
    system: str = "",
    tools: list | None = None,
    timeout: float | None = None,
) -> anthropic.types.Message:
    """Thin wrapper around anthropic.Anthropic().messages.create that tracks tokens."""
    client_kwargs = {"api_key": api_key}
    if timeout is not None:
        client_kwargs["timeout"] = timeout
    client = anthropic.Anthropic(**client_kwargs)
    kwargs = dict(model=model, max_tokens=max_tokens, messages=messages)
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools
    t0 = time.monotonic()
    response = client.messages.create(**kwargs)
    duration_ms = int((time.monotonic() - t0) * 1000)
    in_tok = response.usage.input_tokens
    out_tok = response.usage.output_tokens
    cost = _usage.add(in_tok, out_tok, model)
    short_model = model.split("-")[1] if "-" in model else model  # haiku/sonnet/opus
    log.info("llm", f"💸 {short_model:<7} in={in_tok:<5} out={out_tok:<4} ${cost:.3f}  {duration_ms}ms")
    return response


def _stub_create_message(
    api_key: str,
    model: str,
    max_tokens: int,
    messages: list,
    system: str = "",
    tools: list | None = None,
    timeout: float | None = None,
) -> anthropic.types.Message:
    """Returns canned responses for hermetic testing. No real API call."""
    import json as _json

    # Detect what kind of request this is from the system prompt or message content
    user_text = " ".join(
        str(m.get("content", "")) for m in messages if m.get("role") == "user"
    ).lower()
    system_lower = (system or "").lower()

    if "quiz" in system_lower or "poll" in system_lower or "question" in user_text:
        # Canned quiz response
        quiz_json = _json.dumps({
            "question": "Which design pattern decouples an abstraction from its implementation?",
            "options": ["Bridge", "Adapter", "Facade", "Proxy"],
            "correct": 0,
            "multi": False,
        })
        text = f"```json\n{quiz_json}\n```"
    elif "debate" in system_lower or "argument" in system_lower:
        # Canned debate cleanup response
        text = _json.dumps({
            "merges": [],
            "cleaned": [],
            "new_arguments": [
                {"side": "for", "text": "Improves testability through dependency injection"},
                {"side": "against", "text": "Adds unnecessary complexity for simple cases"},
            ],
        })
    elif "summary" in system_lower or "key point" in system_lower:
        # Canned summary response
        text = _json.dumps({
            "added": [{"text": "Discussed adapter pattern for hermetic testing", "source": "discussion"}],
            "removed": [],
            "edited": [],
        })
    else:
        text = "This is a canned response from the LLM stub adapter."

    log.info("llm", f"🧪 STUB  model={model}  (canned response, no API call)")
    return anthropic.types.Message(
        id="msg_stub_000",
        type="message",
        role="assistant",
        content=[anthropic.types.TextBlock(type="text", text=text)],
        model=model,
        stop_reason="end_turn",
        stop_sequence=None,
        usage=anthropic.types.Usage(input_tokens=100, output_tokens=50),
    )


import os as _os
if _os.environ.get("LLM_ADAPTER") == "stub":
    create_message = _stub_create_message
    log.info("llm", "🧪 Using STUB LLM adapter (no real API calls)")
else:
    create_message = _real_create_message
