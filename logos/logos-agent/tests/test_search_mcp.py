"""The coding agent gets Logos' web search instead of Claude Code's own."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "workspace"))

import run_session  # noqa: E402


@pytest.mark.parametrize("resuming", [False, True])
def test_claude_has_search_tool_on_initial_and_continued_runs(monkeypatch, resuming):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://logos-agent-gateway/")
    command = run_session._agent_command("Task", resuming=resuming)
    config = json.loads(command[command.index("--mcp-config") + 1])
    # The gateway forwards /v1 and replaces the Authorization header, so the
    # session's config names the endpoint and holds no key.
    assert config["mcpServers"]["logos-search"] == {
        "type": "http",
        "url": "http://logos-agent-gateway/v1/web-search/mcp",
    }
    assert command[command.index("--disallowedTools") + 1] == "WebSearch"
    assert ("--continue" in command) == resuming


def test_search_calls_show_their_query():
    assert run_session._tool_detail("mcp__logos-search__web_search", {"query": "asyncio docs"}) == "asyncio docs"
