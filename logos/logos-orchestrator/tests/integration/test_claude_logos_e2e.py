"""End-to-end tests that drive the real ``claude-logos`` wrapper.

Every other test in this PR stubs something: the unit tests translate payloads
in isolation, and the sync tests hand the service a fake model listing. What
none of them prove is the thing the issue was actually about — that Claude
Code, talking to a Logos instance the way a developer's machine does, gets a
working session with the context window the instance really serves.

These tests close that gap by running the wrapper this repo ships
(``logos-ui/public/claude-logos.sh``) against a live instance:

* ``--check`` reads ``GET /v1/models`` and prints the window it will run at.
  On a downstream instance that window used to be missing entirely, so the
  wrapper fell back to its blind constant and the report said "an estimate".
  That line is the regression signal, and it is asserted against directly.
* A headless ``claude-logos -p …`` run puts a real Claude Code session through
  ``POST /v1/messages``, which is the path the Anthropic translation serves.

Both need credentials and a reachable instance, so they are opt-in and skipped
everywhere else — the same treatment ``tests/conftest.py`` gives the other
credential-dependent scripts. ``testpaths`` is ``tests/unit``, so CI does not
collect this file at all.

    LOGOS_IT_URL=https://logos-test.aet.cit.tum.de \
    LOGOS_IT_KEY_FILE=~/.config/claude-logos/key \
    LOGOS_IT_MODEL=Qwen/Qwen3.8-27B \
        poetry run pytest tests/integration/test_claude_logos_e2e.py -v

Point ``LOGOS_IT_URL`` at an instance whose model is served by a **cloud**
provider to exercise the translation; a workernode-backed model takes the
native path and proves only that nothing regressed there.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow]

# tests/integration/<this> -> tests -> logos-orchestrator -> logos
WRAPPER = Path(__file__).resolve().parents[3] / "logos-ui" / "public" / "claude-logos.sh"

# How long a real model turn may take. A cold lane has to load the weights
# before it answers, which dominates everything else here.
TURN_TIMEOUT_S = 600
PROBE_TIMEOUT_S = 60

# The wrapper's blind fallback for a model the gateway reports no window for.
# Seeing it means the instance published no context — the bug these tests
# guard against — so it is never a valid outcome.
BLIND_FALLBACK_TOKENS = 111200


def _which(binary: str) -> Optional[str]:
    return shutil.which(binary)


def _env(name: str) -> Optional[str]:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else None


def _configured_key() -> Optional[str]:
    key = _env("LOGOS_IT_KEY")
    if key:
        return key
    key_file = _env("LOGOS_IT_KEY_FILE")
    if not key_file:
        return None
    path = Path(key_file).expanduser()
    return path.read_text().strip() if path.is_file() else None


LOGOS_URL = (_env("LOGOS_IT_URL") or "").rstrip("/")
LOGOS_KEY = _configured_key()
LOGOS_MODEL = _env("LOGOS_IT_MODEL")

pytestmark.append(
    pytest.mark.skipif(
        not (LOGOS_URL and LOGOS_KEY),
        reason="set LOGOS_IT_URL and LOGOS_IT_KEY / LOGOS_IT_KEY_FILE to run the claude-logos end-to-end tests",
    )
)


# ── helpers ─────────────────────────────────────────────────────────────────


def _post(path: str, payload: Dict[str, Any], *, stream: bool = False):
    request = urllib.request.Request(
        f"{LOGOS_URL}/{path.lstrip('/')}",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {LOGOS_KEY}",
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            "Accept": "text/event-stream" if stream else "application/json",
        },
    )
    return urllib.request.urlopen(request, timeout=TURN_TIMEOUT_S)


def _served_models() -> Dict[str, Dict[str, Any]]:
    request = urllib.request.Request(f"{LOGOS_URL}/v1/models", headers={"Authorization": f"Bearer {LOGOS_KEY}"})
    with urllib.request.urlopen(request, timeout=PROBE_TIMEOUT_S) as response:
        body = json.load(response)
    return {entry["id"]: entry for entry in body.get("data", []) if isinstance(entry, dict)}


@pytest.fixture(scope="module")
def served() -> Dict[str, Dict[str, Any]]:
    try:
        models = _served_models()
    except (urllib.error.URLError, TimeoutError) as exc:
        pytest.skip(f"{LOGOS_URL} is not reachable: {exc}")
    if not models:
        pytest.skip(f"{LOGOS_URL} serves no models for this key")
    return models


@pytest.fixture(scope="module")
def model(served: Dict[str, Dict[str, Any]]) -> str:
    """The model under test: the configured one, else whatever is served."""
    if LOGOS_MODEL:
        if LOGOS_MODEL not in served:
            pytest.skip(f"{LOGOS_MODEL} is not served here; available: {', '.join(sorted(served))}")
        return LOGOS_MODEL
    return sorted(served)[0]


@pytest.fixture(scope="module")
def wrapper_env(tmp_path_factory, model: str) -> Dict[str, str]:
    """Environment for the wrapper, isolated from the developer's own config.

    ``LOGOS_CONFIG_DIR`` is redirected to a temporary directory because the
    wrapper writes its known-models and last-seen-revision state there; a test
    run must not disturb the config an actual session is using.
    """
    config_dir = tmp_path_factory.mktemp("claude-logos-config")
    key_file = config_dir / "key"
    key_file.write_text(LOGOS_KEY)
    key_file.chmod(0o600)
    return {
        **os.environ,
        "LOGOS_CONFIG_DIR": str(config_dir),
        "LOGOS_KEY_FILE": str(key_file),
        "LOGOS_URL": LOGOS_URL,
        "LOGOS_MODEL": model,
    }


def _run_wrapper(env: Dict[str, str], *args: str, timeout: int) -> subprocess.CompletedProcess:
    assert WRAPPER.is_file(), f"wrapper not found at {WRAPPER}"
    return subprocess.run(
        ["bash", str(WRAPPER), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _reported_tokens(check_output: str) -> int:
    """The context size the wrapper's report says the session will run at."""
    match = re.search(r"^context\s*:\s*([\d,]+) tokens", check_output, re.MULTILINE)
    assert match, f"no context line in the report:\n{check_output}"
    return int(match.group(1).replace(",", ""))


# ── the wrapper's own view ──────────────────────────────────────────────────


def test_check_reports_a_context_window_the_instance_actually_serves(wrapper_env, model, served):
    """``--check`` must not fall back to its blind constant.

    This is the reported symptom in its original form: against a downstream
    instance the model list carried no window, so the wrapper guessed. The
    guess is far under a 262144-token model and far over a 32768-token one,
    which is why "it does not work with full context".
    """
    result = _run_wrapper(wrapper_env, "--check", timeout=PROBE_TIMEOUT_S)
    assert result.returncode == 0, result.stderr or result.stdout
    report = result.stdout

    assert "Logos reports no size for this model" not in report, report
    assert f"model    : {model}" in report
    assert f"logos    : {LOGOS_URL}" in report

    reported = _reported_tokens(report)
    entry = served[model]
    # The wrapper defaults to LOGOS_CONTEXT_SOURCE=available, i.e. the largest
    # window currently reachable, and falls back down the same cascade the
    # instance publishes.
    expected = (
        entry.get("max_model_len_current_max")
        or entry.get("max_model_len_current_min")
        or entry.get("max_model_len")
        or entry.get("max_model_len_overall")
    )
    assert expected, f"{LOGOS_URL} publishes no context window for {model}: {entry}"
    assert reported == expected
    assert reported != BLIND_FALLBACK_TOKENS or expected == BLIND_FALLBACK_TOKENS


def test_check_reports_no_blocking_condition(wrapper_env):
    """A window that cannot host a session is reported, not silently accepted."""
    result = _run_wrapper(wrapper_env, "--check", timeout=PROBE_TIMEOUT_S)
    assert "BLOCKED" not in result.stdout, result.stdout
    assert "is not served here" not in result.stdout, result.stdout


# ── a real Claude Code session ──────────────────────────────────────────────


def test_headless_session_answers_through_the_messages_api(wrapper_env):
    """A real Claude Code turn, start to finish, through POST /v1/messages.

    Claude Code sends its full system prompt and tool definitions on the first
    turn, so this covers the request shapes the translation has to survive —
    a block-list system prompt and a large ``tools`` array — rather than the
    hand-written payloads the unit tests use.
    """
    if not _which("claude"):
        pytest.skip("Claude Code is not installed; install it to run the headless session test")

    result = _run_wrapper(
        wrapper_env,
        "-p",
        "Reply with exactly the word READY and nothing else.",
        timeout=TURN_TIMEOUT_S,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "READY" in result.stdout.upper(), result.stdout


# ── the Messages surface itself ─────────────────────────────────────────────


def test_messages_returns_an_anthropic_message(model):
    """The wire shape a client parses, from whichever upstream serves it."""
    with _post(
        "v1/messages",
        {
            "model": model,
            "max_tokens": 32,
            "system": [{"type": "text", "text": "Answer in one word."}],
            "messages": [{"role": "user", "content": [{"type": "text", "text": "Say OK."}]}],
        },
    ) as response:
        body = json.load(response)

    assert body["type"] == "message"
    assert body["role"] == "assistant"
    assert body["content"], body
    assert body["content"][0]["type"] == "text"
    assert body["stop_reason"] in ("end_turn", "max_tokens", "stop_sequence", "tool_use")
    assert body["usage"]["input_tokens"] > 0
    assert body["usage"]["output_tokens"] > 0


def test_messages_streams_the_anthropic_event_sequence(model):
    """Anthropic framing, in order, with a usage-bearing terminal event.

    A translated stream is assembled event by event, so the ordering and the
    terminal token count are what a client actually depends on — and what a
    forwarded OpenAI stream would have broken.
    """
    events = []
    with _post(
        "v1/messages",
        {
            "model": model,
            "max_tokens": 32,
            "messages": [{"role": "user", "content": "Count to three."}],
            "stream": True,
        },
        stream=True,
    ) as response:
        block: list[str] = []
        for raw in response:
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            if line:
                block.append(line)
                continue
            name = next((entry[7:] for entry in block if entry.startswith("event: ")), None)
            data = next((entry[6:] for entry in block if entry.startswith("data: ")), None)
            if name:
                events.append((name, json.loads(data) if data else None))
            block = []

    names = [name for name, _ in events]
    assert names[0] == "message_start", names[:4]
    assert names[-1] == "message_stop", names[-4:]
    assert "content_block_start" in names and "content_block_stop" in names
    # OpenAI's terminal sentinel is not part of the Messages protocol; leaking
    # it means the stream was forwarded rather than translated.
    assert "[DONE]" not in names

    answer = "".join(
        data["delta"]["text"]
        for name, data in events
        if name == "content_block_delta" and data and data["delta"].get("type") == "text_delta"
    )
    assert answer.strip(), events

    stop = next(data for name, data in events if name == "message_delta")
    assert stop["delta"]["stop_reason"] in ("end_turn", "max_tokens", "stop_sequence", "tool_use")
    assert stop["usage"]["output_tokens"] > 0


def test_models_publishes_a_context_window(model, served):
    """What the wrapper reads at startup — the fix for the missing window."""
    entry = served[model]
    assert any(
        entry.get(field) for field in ("max_model_len", "max_model_len_current_min", "max_model_len_overall")
    ), f"no context window published for {model}: {entry}"
