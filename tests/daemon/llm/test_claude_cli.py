"""daemon/llm/claude_cli.py: the LLM calls go through the Claude subscription's CLI."""
import json
import subprocess

import pytest

from daemon.llm import claude_cli


def _run_returning(out: dict, seen: dict, returncode: int = 0):
    def run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["env"] = kwargs["env"]
        seen["input"] = kwargs["input"]
        return subprocess.CompletedProcess(cmd, returncode, stdout=json.dumps(out), stderr="")
    return run


OK = {"is_error": False, "result": '{"n": 3}', "structured_output": {"n": 3}, "total_cost_usd": 0.0003,
      "modelUsage": {"claude-haiku-5-5": {"inputTokens": 2, "cacheReadInputTokens": 10,
                                          "cacheCreationInputTokens": 100, "outputTokens": 7}}}


def test_asks_a_bare_cli_on_the_subscription(monkeypatch):
    seen = {}
    monkeypatch.setattr(claude_cli, "find_cli", lambda: "/bin/claude")
    monkeypatch.setattr(subprocess, "run", _run_returning(OK, seen))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-paid")
    answer = claude_cli.ask("count", system="be terse", model="claude-haiku-4-5-20251001",
                            json_schema={"type": "object"}, effort="low")
    assert answer.data == {"n": 3} and answer.text == '{"n": 3}'
    assert (answer.input_tokens, answer.output_tokens, answer.model) == (112, 7, "claude-haiku-5-5")
    cmd = seen["cmd"]
    assert cmd[:2] == ["/bin/claude", "-p"] and cmd[cmd.index("--model") + 1] == "haiku"
    assert cmd[cmd.index("--tools") + 1] == "" and "--strict-mcp-config" in cmd
    assert cmd[cmd.index("--system-prompt") + 1] == "be terse" and "--json-schema" in cmd
    assert seen["input"] == "count"
    assert "ANTHROPIC_API_KEY" not in seen["env"]  # an API key would win over the subscription


def test_a_failed_answer_raises(monkeypatch):
    monkeypatch.setattr(claude_cli, "find_cli", lambda: "/bin/claude")
    monkeypatch.setattr(subprocess, "run", _run_returning({"is_error": True, "result": "rate limited"}, {}, 1))
    with pytest.raises(RuntimeError, match="rate limited"):
        claude_cli.ask("x", system="s", model="sonnet")


def test_no_cli_raises(monkeypatch):
    monkeypatch.setattr(claude_cli, "find_cli", lambda: None)
    with pytest.raises(RuntimeError, match="not found"):
        claude_cli.ask("x", system="s", model="sonnet")
