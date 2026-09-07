"""The shipped ``claude-logos`` wrapper, driven end to end against a stub.

Everything else in this PR tests the orchestrator. This tests the other half
of the reported problem: the client. ``claude-logos`` reads ``GET /v1/models``
at startup, sizes the session from the window it finds there and then execs
Claude Code with that window — so a gateway that publishes no window, which is
what a downstream instance used to do, silently drops the session onto the
wrapper's blind fallback constant.

Nothing here talks to a real deployment. A stub gateway runs on loopback for
the length of each test and a fake ``claude`` on ``PATH`` stands in for Claude
Code, which makes the whole path — model list, context arithmetic, exported
environment, the request Claude Code would send — reproducible and available
in CI. That matters beyond the context window: the launch tests below are what
catch the wrapper failing to start at all.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

import pytest

# tests/unit/wrapper/<this> -> unit -> tests -> logos-orchestrator -> logos
WRAPPER = Path(__file__).resolve().parents[4] / "logos-ui" / "public" / "claude-logos.sh"

# The wrapper's fallback for a model the gateway reports no window for. A guess
# for every model at once, so it is wrong in both directions; seeing it means
# the gateway published nothing.
BLIND_FALLBACK_TOKENS = 111200

WIDE_WINDOW = 262144

MODEL = "Qwen/Qwen3.8-27B"


def _model_entry(name: str, window: Optional[int]) -> Dict[str, Any]:
    """One ``GET /v1/models`` entry, with or without a context window."""
    entry: Dict[str, Any] = {"id": name, "object": "model", "created": 1, "owned_by": "logos"}
    if window:
        entry.update(
            max_model_len=window,
            max_model_len_current_min=window,
            max_model_len_current_max=window,
            max_model_len_overall=window,
        )
    return entry


class _StubGateway:
    """A Logos-shaped gateway: the model list, warmup, and Messages."""

    def __init__(self, models: list[Dict[str, Any]]):
        self.models = models
        self.requests: list[Dict[str, Any]] = []
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def url(self) -> str:
        assert self._server is not None
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> None:
        stub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):  # keep pytest output readable
                pass

            def _send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _record(self, payload: Any = None) -> None:
                stub.requests.append(
                    {
                        "method": self.command,
                        "path": self.path,
                        "authorization": self.headers.get("Authorization"),
                        "payload": payload,
                    }
                )

            def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler's spelling
                self._record()
                if self.path == "/v1/models":
                    self._send(200, json.dumps({"object": "list", "data": stub.models}).encode())
                    return
                # The wrapper fetches this to notice a newer revision; a 404 is
                # a normal answer and it carries on.
                self._send(404, b'{"error":"not found"}')

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    payload = json.loads(raw) if raw else None
                except ValueError:
                    payload = None
                self._record(payload)

                if self.path == "/v1/messages":
                    self._send(
                        200,
                        json.dumps(
                            {
                                "id": "msg_stub",
                                "type": "message",
                                "role": "assistant",
                                "model": (payload or {}).get("model", ""),
                                "content": [{"type": "text", "text": "READY"}],
                                "stop_reason": "end_turn",
                                "usage": {"input_tokens": 7, "output_tokens": 1},
                            }
                        ).encode(),
                    )
                    return
                self._send(200, b"{}")

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def paths(self) -> list[str]:
        return [f"{entry['method']} {entry['path']}" for entry in self.requests]


@pytest.fixture
def gateway() -> Iterator[_StubGateway]:
    stub = _StubGateway([_model_entry(MODEL, WIDE_WINDOW)])
    stub.start()
    try:
        yield stub
    finally:
        stub.stop()


@pytest.fixture
def windowless_gateway() -> Iterator[_StubGateway]:
    """A gateway that lists the model but publishes no context window.

    What a downstream Logos instance did before this PR: the model is
    reachable, but its window is invisible.
    """
    stub = _StubGateway([_model_entry(MODEL, None)])
    stub.start()
    try:
        yield stub
    finally:
        stub.stop()


# ``exec``-ed in place of Claude Code. It records how it was invoked, and — so
# the wrapper's wiring is proven rather than assumed — sends the request Claude
# Code would send, to the base URL and with the credential it was handed.
FAKE_CLAUDE = """#!/usr/bin/env python3
import json, os, sys, urllib.request

record = {
    "argv": sys.argv[1:],
    "env": {
        name: os.environ.get(name)
        for name in (
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_AUTH_TOKEN",
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_MODEL",
            "CLAUDE_CODE_MAX_CONTEXT_TOKENS",
            "CLAUDE_CODE_MAX_OUTPUT_TOKENS",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
        )
    },
}

if os.environ.get("FAKE_CLAUDE_CALL_MESSAGES") == "1":
    request = urllib.request.Request(
        os.environ["ANTHROPIC_BASE_URL"].rstrip("/") + "/v1/messages",
        data=json.dumps(
            {
                "model": os.environ.get("ANTHROPIC_MODEL", ""),
                "max_tokens": 16,
                "messages": [{"role": "user", "content": "ping"}],
            }
        ).encode(),
        headers={
            "Authorization": "Bearer " + (os.environ.get("ANTHROPIC_AUTH_TOKEN") or ""),
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.load(response)
    record["answer"] = "".join(
        block.get("text", "") for block in body.get("content", []) if block.get("type") == "text"
    )

with open(os.environ["FAKE_CLAUDE_RECORD"], "w") as handle:
    json.dump(record, handle)
print(record.get("answer", "fake-claude ok"))
"""


@pytest.fixture
def fake_claude(tmp_path: Path) -> Path:
    """A ``claude`` on PATH that records its invocation. Returns the record path."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    binary = bin_dir / "claude"
    binary.write_text(FAKE_CLAUDE)
    binary.chmod(0o755)
    return bin_dir


def _env(
    gateway: _StubGateway,
    tmp_path: Path,
    *,
    fake_claude_dir: Optional[Path] = None,
    record: Optional[Path] = None,
    settings: bool = True,
    **extra: str,
) -> Dict[str, str]:
    """Environment for one wrapper run, isolated from the developer's config."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    key_file = config_dir / "key"
    key_file.write_text("lg-stub-key")
    if settings:
        (config_dir / "settings.json").write_text("{}")

    env = {
        **os.environ,
        "LOGOS_CONFIG_DIR": str(config_dir),
        "LOGOS_KEY_FILE": str(key_file),
        "LOGOS_URL": gateway.url,
        "LOGOS_MODEL": MODEL,
        # The wrapper checks for a newer revision at most once per interval;
        # a long one keeps the (harmless, backgrounded) fetch out of the way.
        "LOGOS_VERSION_CHECK_INTERVAL": "86400",
        **extra,
    }
    if fake_claude_dir is not None:
        env["PATH"] = f"{fake_claude_dir}{os.pathsep}{os.environ['PATH']}"
    if record is not None:
        env["FAKE_CLAUDE_RECORD"] = str(record)
    return env


def _run(env: Dict[str, str], *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    assert WRAPPER.is_file(), f"wrapper not found at {WRAPPER}"
    return subprocess.run(
        [shutil.which("bash") or "bash", str(WRAPPER), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _reported_tokens(report: str) -> int:
    match = re.search(r"^context\s*:\s*([\d,]+) tokens", report, re.MULTILINE)
    assert match, f"no context line in the report:\n{report}"
    return int(match.group(1).replace(",", ""))


# ── the context window the session gets ─────────────────────────────────────


def test_check_uses_the_window_the_gateway_publishes(gateway, tmp_path):
    """The fix, seen from the client: a published window is the one used."""
    result = _run(_env(gateway, tmp_path), "--check")
    assert result.returncode == 0, result.stderr

    assert _reported_tokens(result.stdout) == WIDE_WINDOW
    assert "Logos reports no size for this model" not in result.stdout
    assert f"model    : {MODEL}" in result.stdout
    assert "GET /v1/models" in gateway.paths()


def test_check_falls_back_to_a_guess_when_no_window_is_published(windowless_gateway, tmp_path):
    """The bug, seen from the client.

    This is what a downstream instance served before the orchestrator learned
    to republish its upstream's window: the model is listed, so the session
    starts, but it is sized from a constant that has nothing to do with the
    model — far under a 262144-token one, far over a 32768-token one.
    """
    result = _run(_env(windowless_gateway, tmp_path), "--check")
    assert result.returncode == 0, result.stderr

    assert _reported_tokens(result.stdout) == BLIND_FALLBACK_TOKENS
    assert "Logos reports no size for this model" in result.stdout


def test_context_source_selects_among_the_published_windows(tmp_path):
    """``guaranteed`` takes the smallest window, ``max`` the widest."""
    stub = _StubGateway(
        [
            {
                "id": MODEL,
                "object": "model",
                "owned_by": "logos",
                "max_model_len": 33000,
                "max_model_len_current_min": 33000,
                "max_model_len_current_max": 120000,
                "max_model_len_overall": WIDE_WINDOW,
            }
        ]
    )
    stub.start()
    try:
        by_source = {
            source: _reported_tokens(_run(_env(stub, tmp_path, LOGOS_CONTEXT_SOURCE=source), "--check").stdout)
            for source in ("guaranteed", "available", "max")
        }
    finally:
        stub.stop()

    assert by_source == {"guaranteed": 33000, "available": 120000, "max": WIDE_WINDOW}


def test_check_warns_about_a_model_the_gateway_does_not_serve(gateway, tmp_path):
    result = _run(_env(gateway, tmp_path, LOGOS_MODEL="not/served"), "--check")
    assert "is not served here" in result.stdout
    assert MODEL in result.stdout  # the ids it could have used


# ── launching Claude Code ───────────────────────────────────────────────────


def test_launch_hands_claude_code_the_gateway_and_the_window(gateway, tmp_path, fake_claude):
    """What the wrapper exports is what Claude Code runs with."""
    record = tmp_path / "record.json"
    result = _run(_env(gateway, tmp_path, fake_claude_dir=fake_claude, record=record), "-p", "hi")
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"

    invocation = json.loads(record.read_text())
    env = invocation["env"]
    assert env["ANTHROPIC_BASE_URL"] == gateway.url
    assert env["ANTHROPIC_AUTH_TOKEN"] == "lg-stub-key"
    # x-api-key would be sent instead of Authorization, which the orchestrator
    # does not read.
    assert env["ANTHROPIC_API_KEY"] is None
    assert env["ANTHROPIC_MODEL"] == MODEL
    assert env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"

    # Sized from the published window, minus the reply reservation and margin,
    # so it must be under the window and well above the fallback.
    context = int(env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"])
    assert BLIND_FALLBACK_TOKENS < context <= WIDE_WINDOW

    assert invocation["argv"][-2:] == ["-p", "hi"]


def test_launch_survives_an_empty_settings_and_effort_argument_list(gateway, tmp_path, fake_claude):
    """Both optional argument arrays empty — the wrapper must still start.

    ``exec claude "${settings_args[@]}" …`` aborts under ``set -u`` on bash 3.2,
    which is what macOS ships, so this combination — no readable settings file
    and an ``--effort`` supplied by the caller, which drops the wrapper's own —
    refused to start a session at all.
    """
    record = tmp_path / "record.json"
    env = _env(gateway, tmp_path, fake_claude_dir=fake_claude, record=record, settings=False)
    result = _run(env, "--effort", "low", "-p", "hi")

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "unbound variable" not in result.stderr

    invocation = json.loads(record.read_text())
    assert "--settings" not in invocation["argv"]
    # The caller's --effort is passed through once, not doubled up.
    assert invocation["argv"].count("--effort") == 1


def test_wrapper_guards_every_array_expansion(tmp_path):
    """No unguarded ``"${arr[@]}"`` anywhere in the wrapper.

    The functional test above only reproduces the failure on bash 3.2; CI runs
    bash 5, where an empty array expands fine. This catches the whole class on
    any platform, the same way ``run_tests.sh`` already writes it.
    """
    source = WRAPPER.read_text()
    unguarded = [
        line
        for line in source.splitlines()
        if re.search(r'"\$\{[A-Za-z_][A-Za-z0-9_]*\[@\]\}"', line)
        and not re.search(r"\$\{[A-Za-z_][A-Za-z0-9_]*\[@\]\+", line)
    ]
    assert not unguarded, 'use ${arr[@]+"${arr[@]}"} — bash 3.2 aborts otherwise:\n' + "\n".join(unguarded)


def test_launch_reaches_the_messages_api_with_the_exported_credential(gateway, tmp_path, fake_claude):
    """The whole path, end to end: wrapper -> environment -> POST /v1/messages.

    The stand-in for Claude Code sends the request Claude Code would send,
    using only what the wrapper put in its environment, so this covers the
    wiring rather than asserting on it.
    """
    record = tmp_path / "record.json"
    env = _env(
        gateway,
        tmp_path,
        fake_claude_dir=fake_claude,
        record=record,
        FAKE_CLAUDE_CALL_MESSAGES="1",
    )
    result = _run(env, "-p", "hi")
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"

    assert json.loads(record.read_text())["answer"] == "READY"
    assert "READY" in result.stdout

    message_requests = [entry for entry in gateway.requests if entry["path"] == "/v1/messages"]
    assert len(message_requests) == 1
    assert message_requests[0]["authorization"] == "Bearer lg-stub-key"
    assert message_requests[0]["payload"]["model"] == MODEL


def test_launch_warms_the_model_up(gateway, tmp_path, fake_claude):
    """The wrapper asks the gateway to start loading before the first turn."""
    record = tmp_path / "record.json"
    _run(_env(gateway, tmp_path, fake_claude_dir=fake_claude, record=record), "-p", "hi")
    assert any(entry["path"].endswith("/warmup") for entry in gateway.requests), gateway.paths()


def test_check_makes_no_inference_request(gateway, tmp_path):
    """``--check`` is metadata only — it must not cost a model load."""
    _run(_env(gateway, tmp_path), "--check")
    assert not [entry for entry in gateway.requests if entry["path"] == "/v1/messages"]
    assert not [entry for entry in gateway.requests if entry["path"].endswith("/warmup")]
