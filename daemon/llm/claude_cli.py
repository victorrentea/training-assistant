"""Claude through the trainer's Claude subscription: `claude -p`, not the paid API.

The daemon runs on his Mac, where Claude Code is logged in to his subscription, so
its few LLM calls (debate cleanup, smart paste) go through the CLI headless instead
of an API key that bills per token and stops dead once its credit runs out (Victor, 2026-10-22). Each call starts a bare CLI: no tools, no MCP servers,
no settings or hooks, no saved session, our own system prompt. It costs ~3 s of
start-up on top of the model's answer, fine for calls that run in the background.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

# Env vars that would steer the CLI off the subscription (an API key wins over the
# login) or make it think it runs inside another Claude Code session.
_SCRUBBED_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDECODE", "CLAUDE_CODE_SESSION_ID",
                 "CLAUDE_CODE_ENTRYPOINT")


@dataclass
class Answer:
    text: str  # the model's reply
    data: dict | None  # the reply parsed, when a JSON schema was asked for
    model: str
    input_tokens: int  # including cache reads and writes
    output_tokens: int
    list_cost_usd: float  # what it would cost on the API; the subscription doesn't charge it


def find_cli() -> str | None:
    """The `claude` binary, also when the daemon's PATH lacks ~/.local/bin."""
    found = shutil.which("claude")
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / "claude"
    return str(fallback) if fallback.exists() else None


def model_alias(model: str) -> str:
    """A pinned id like claude-haiku-4-5-20251001 → its family alias, so an old id in
    the code or env still gets the current model of that family."""
    for family in ("haiku", "sonnet", "opus"):
        if family in model:
            return family
    return model


def ask(prompt: str, *, system: str, model: str, json_schema: dict | None = None,
        effort: str | None = None, timeout: float = 180.0) -> Answer:
    """One question, one answer. Raises RuntimeError when the CLI is missing or fails."""
    cli = find_cli()
    if not cli:
        raise RuntimeError("Claude Code CLI not found (claude)")
    cmd = [cli, "-p", "--model", model_alias(model), "--output-format", "json",
           "--system-prompt", system, "--tools", "", "--no-session-persistence",
           "--setting-sources", "", "--strict-mcp-config"]
    if json_schema is not None:
        cmd += ["--json-schema", json.dumps(json_schema)]
    if effort:
        cmd += ["--effort", effort]
    env = {k: v for k, v in os.environ.items() if k not in _SCRUBBED_ENV}
    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout,
                          env=env, cwd=tempfile.gettempdir())
    try:
        out = json.loads(proc.stdout)
    except ValueError:
        raise RuntimeError(f"claude -p exit {proc.returncode}: {(proc.stderr or proc.stdout).strip()[:300]}")
    if proc.returncode != 0 or out.get("is_error"):
        raise RuntimeError(f"claude -p failed: {str(out.get('result') or out.get('subtype'))[:300]}")
    usage = out.get("modelUsage") or {}
    used = next(iter(usage), model)
    tokens = usage.get(used, {})
    data = out.get("structured_output")
    return Answer(
        text=str(out.get("result") or ""),
        data=data if isinstance(data, dict) else None,
        model=used,
        input_tokens=sum(int(tokens.get(k, 0)) for k in
                         ("inputTokens", "cacheReadInputTokens", "cacheCreationInputTokens")),
        output_tokens=int(tokens.get("outputTokens", 0)),
        list_cost_usd=float(out.get("total_cost_usd") or 0.0),
    )
