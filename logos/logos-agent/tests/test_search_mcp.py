"""The coding agent can discover and call search through the model gateway."""

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "workspace"))

import run_session  # noqa: E402


def test_mcp_process_discovers_and_calls_search(monkeypatch):
    received = []
    result = {"query": "Python", "source": "DuckDuckGo", "results": [{"title": "Docs", "url": "https://python.org"}]}

    class Gateway(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"]))), self.headers))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Gateway)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("ANTHROPIC_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    messages = [
        {"id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
        {"method": "notifications/initialized"},
        {"id": 2, "method": "tools/list"},
        {"id": 3, "method": "tools/call", "params": {"name": "web_search", "arguments": {"query": " Python "}}},
        {"id": 4, "method": "ping"},
    ]
    try:
        process = subprocess.run(
            [sys.executable, run_session.__file__, "--web-search-mcp"],
            input="".join(json.dumps({"jsonrpc": "2.0", **message}) + "\n" for message in messages),
            capture_output=True,
            text=True,
            timeout=10,
            env=os.environ.copy(),
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert process.returncode == 0, process.stderr
    replies = [json.loads(line) for line in process.stdout.splitlines()]
    assert [reply["id"] for reply in replies] == [1, 2, 3, 4]
    assert replies[0]["result"]["capabilities"] == {"tools": {}}
    assert replies[1]["result"]["tools"][0]["name"] == "web_search"
    assert json.loads(replies[2]["result"]["content"][0]["text"]) == result
    assert received[0][0:2] == ("/v1/web-search", {"query": "Python", "max_results": 5})
    assert received[0][2].get("Authorization") is None


@pytest.mark.parametrize("resuming", [False, True])
def test_claude_has_search_tool_on_initial_and_continued_runs(resuming):
    command = run_session._agent_command("Task", resuming=resuming)
    config = json.loads(command[command.index("--mcp-config") + 1])
    assert config["mcpServers"]["logos-search"] == {
        "command": sys.executable,
        "args": [run_session.__file__, "--web-search-mcp"],
    }
    assert "mcp__logos-search__web_search" in command[command.index("--append-system-prompt") + 1]
    assert ("--continue" in command) == resuming


@pytest.mark.parametrize("arguments", [{}, {"query": " "}, {"query": "x" * 501}, {"query": "x", "max_results": True}])
def test_invalid_tool_arguments_do_not_reach_gateway(monkeypatch, arguments):
    http = Mock()
    monkeypatch.setattr(run_session, "urlopen", http)
    assert run_session._search_tool_call(arguments)["isError"] is True
    http.assert_not_called()


@pytest.mark.parametrize("error", [HTTPError("http://gateway", 503, "Unavailable", None, None), URLError("offline")])
def test_gateway_errors_are_tool_errors(monkeypatch, error):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://gateway")
    monkeypatch.setattr(run_session, "urlopen", Mock(side_effect=error))
    response = run_session._search_tool_call({"query": "Python"})
    assert response["isError"] is True
    assert "gateway" in response["content"][0]["text"]


def test_invalid_and_unknown_mcp_requests():
    assert run_session._search_mcp_response({"method": "notifications/initialized"}) is None
    assert run_session._search_mcp_response({"id": 1, "method": "unknown"})["error"]["code"] == -32601
    assert run_session._search_mcp_response({"id": 2, "method": "tools/call", "params": []})["error"]["code"] == -32602


def test_mcp_parse_error_does_not_stop_next_request(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", StringIO('invalid\n{"id": 1, "method": "ping"}\n'))
    assert run_session.run_search_mcp() == 0
    responses = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert responses[0]["error"]["code"] == -32700
    assert responses[1]["result"] == {}


@pytest.mark.parametrize("data", [b"not JSON", b"x" * 64_001])
def test_invalid_or_oversized_gateway_response_is_a_tool_error(monkeypatch, data):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://gateway")
    monkeypatch.setattr(run_session, "urlopen", lambda *_args, **_kwargs: BytesIO(data))
    assert run_session._search_tool_call({"query": "Python"})["isError"] is True
