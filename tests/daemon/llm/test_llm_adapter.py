from daemon.llm.adapter import TokenUsage, PRICING


def test_token_usage_zero():
    u = TokenUsage()
    assert u.input_tokens == 0
    assert u.output_tokens == 0
    assert u.estimated_cost_usd == 0.0


def test_token_usage_accumulates():
    u = TokenUsage()
    u.add(1000, 500, "claude-sonnet-4-6")
    u.add(2000, 300, "claude-sonnet-4-6")
    assert u.input_tokens == 3000
    assert u.output_tokens == 800


def test_token_usage_cost_calculation():
    u = TokenUsage()
    u.add(1_000_000, 0)  # 1M input tokens
    assert abs(u.estimated_cost_usd - 3.0) < 0.01  # $3/1M input for sonnet


def test_to_dict():
    u = TokenUsage()
    u.add(100, 50)
    d = u.to_dict()
    assert "input_tokens" in d
    assert "output_tokens" in d
    assert "estimated_cost_usd" in d
    assert d["input_tokens"] == 100
