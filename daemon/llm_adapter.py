from dataclasses import dataclass, field
from typing import Optional
import anthropic

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

    def add(self, input_tokens: int, output_tokens: int, model: str = ""):
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        # Compute cost using model-specific pricing
        pricing = PRICING.get(model, PRICING["claude-sonnet-4-6"])
        self.estimated_cost_usd += (
            input_tokens * pricing["input"] + output_tokens * pricing["output"]
        ) / 1_000_000

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


def create_message(
    api_key: str,
    model: str,
    max_tokens: int,
    messages: list,
    system: str = "",
    tools: list | None = None,
) -> anthropic.types.Message:
    """Thin wrapper around anthropic.Anthropic().messages.create that tracks tokens."""
    client = anthropic.Anthropic(api_key=api_key)
    kwargs = dict(model=model, max_tokens=max_tokens, messages=messages)
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools
    response = client.messages.create(**kwargs)
    _usage.add(response.usage.input_tokens, response.usage.output_tokens, model)
    return response
