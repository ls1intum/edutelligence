"""The client for the cordon of the node, against a real HTTP server on the loopback interface.

The server answers from a script, like the fake orchestrator of the deployer tests, so the requests that the client
builds and the way it reads answers and failures are tested for real, not through a stand-in.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from logos_node_manager.config import Settings
from logos_node_manager.orchestrator import (
    API_PATH,
    CordonReply,
    NodeStatus,
    OrchestratorClient,
    OrchestratorUnavailable,
)

KEY = "the-secret-node-key"


class ScriptedServer:
    """Answers each request with the next entry of ``script``; the last entry stays.

    An entry is ``(status, body)``. A body that is not a string is sent as JSON.
    """

    def __init__(self) -> None:
        self.script: list[tuple[int, object]] = [(200, {})]
        self.requests: list[dict] = []
        self.delay_s = 0.0
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - the name http.server looks for
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                owner.requests.append({"path": self.path, "body": json.loads(body), "headers": dict(self.headers)})
                if owner.delay_s:
                    time.sleep(owner.delay_s)
                status, payload = owner.script.pop(0) if len(owner.script) > 1 else owner.script[0]
                data = payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args) -> None:
                return None

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        # A short poll interval keeps the shutdown at the end of every test from waiting half a second.
        self._thread = threading.Thread(target=lambda: self._server.serve_forever(poll_interval=0.02), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


@pytest.fixture
def server():
    scripted = ScriptedServer()
    yield scripted
    scripted.stop()


@pytest.fixture
def client(server) -> OrchestratorClient:
    return OrchestratorClient(server.url, KEY, timeout_s=2.0)


# ---------------------------------------------------------------------- The requests


def test_a_call_sends_the_key_and_the_deployment_in_the_body_to_the_node_maintenance_path(server, client):
    server.script = [(200, {"status": "released"})]

    client.release("run-1-2")

    (request,) = server.requests
    assert request["path"] == f"{API_PATH}/release"
    assert request["body"] == {"shared_key": KEY, "deployment_id": "run-1-2"}
    assert request["headers"]["Content-Type"] == "application/json"


def test_each_call_goes_to_its_own_path(server, client):
    server.script = [(200, {"status": "granted"}), (200, {"status": "leased"}), (200, {"status": "released"})]

    client.cordon("d1")
    client.status("d1")
    client.release("d1")

    assert [request["path"].rsplit("/", 1)[1] for request in server.requests] == ["cordon", "status", "release"]


def test_a_trailing_slash_of_the_address_does_not_double_the_slash(server):
    server.script = [(200, {"status": "released"})]

    OrchestratorClient(server.url + "/", KEY).release("d1")

    assert server.requests[0]["path"] == f"{API_PATH}/release"


# ---------------------------------------------------------------------- The answers


def test_a_granted_cordon_carries_the_state_of_the_node(server, client):
    server.script = [
        (
            200,
            {
                "status": "granted",
                "drained": False,
                "online": True,
                "session_id": "abc123",
                "first_status_received": True,
                "in_flight": {"orchestrator": 2, "worker": 1},
                "sole_replica_models": ["model-a", "model-b"],
                "idle_for_s": 0.0,
            },
        )
    ]

    assert client.cordon("d1") == CordonReply(
        granted=True,
        drained=False,
        online=True,
        session_id="abc123",
        in_flight_orchestrator=2,
        in_flight_worker=1,
        sole_replica_models=("model-a", "model-b"),
    )


def test_a_drained_node_is_drained(server, client):
    server.script = [(200, {"status": "granted", "drained": True, "online": True, "session_id": "abc123"})]

    reply = client.cordon("d1")

    assert reply.granted and reply.drained


def test_a_denied_cordon_says_why_and_who_holds_it(server, client):
    server.script = [(200, {"status": "denied", "reason": "another_node_in_maintenance", "holder": "node-b"})]

    assert client.cordon("d1") == CordonReply(granted=False, reason="another_node_in_maintenance", holder="node-b")


def test_a_drain_is_never_assumed_from_a_missing_field(server, client):
    server.script = [(200, {"status": "granted"})]

    assert client.cordon("d1").drained is False


def test_the_status_of_the_node(server, client):
    server.script = [
        (200, {"status": "leased", "online": True, "first_status_received": True, "session_id": "new-session"})
    ]

    assert client.status("d1") == NodeStatus(online=True, first_status_received=True, session_id="new-session")


def test_a_node_the_orchestrator_does_not_see_is_not_online(server, client):
    server.script = [(200, {"status": "no_lease", "online": False, "first_status_received": False, "session_id": None})]

    assert client.status("d1") == NodeStatus(online=False, first_status_received=False, session_id=None)


# ---------------------------------------------------------------------- Failures


@pytest.mark.parametrize("status", [500, 502, 503, 429])
def test_a_server_error_may_pass(server, client, status):
    server.script = [(status, {"detail": "try later"})]

    with pytest.raises(OrchestratorUnavailable) as exc_info:
        client.cordon("d1")

    assert exc_info.value.retryable is True
    assert str(status) in str(exc_info.value)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_an_answer_that_asking_again_will_not_change_is_not_retried(server, client, status):
    server.script = [(status, {"detail": "Provider not found for this API key"})]

    with pytest.raises(OrchestratorUnavailable) as exc_info:
        client.cordon("d1")

    assert exc_info.value.retryable is False
    assert "Provider not found for this API key" in str(exc_info.value)


def test_a_long_reason_is_cut(server, client):
    server.script = [(400, {"detail": "x" * 5000})]

    with pytest.raises(OrchestratorUnavailable) as exc_info:
        client.cordon("d1")

    assert len(str(exc_info.value)) < 300


def test_an_orchestrator_that_is_not_there_may_come_back():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    client = OrchestratorClient(f"http://127.0.0.1:{port}", KEY, timeout_s=1.0)

    with pytest.raises(OrchestratorUnavailable) as exc_info:
        client.cordon("d1")

    assert exc_info.value.retryable is True
    assert KEY not in str(exc_info.value)


def test_an_orchestrator_that_does_not_answer_in_time_may_come_back(server):
    server.delay_s = 1.0
    client = OrchestratorClient(server.url, KEY, timeout_s=0.2)

    with pytest.raises(OrchestratorUnavailable) as exc_info:
        client.cordon("d1")

    assert exc_info.value.retryable is True


def test_an_answer_that_is_not_json_may_pass(server, client):
    server.script = [(200, "<html>bad gateway</html>")]

    with pytest.raises(OrchestratorUnavailable) as exc_info:
        client.cordon("d1")

    assert exc_info.value.retryable is True


def test_an_answer_that_is_not_an_object_is_refused(server, client):
    server.script = [(200, ["granted"])]

    with pytest.raises(OrchestratorUnavailable) as exc_info:
        client.cordon("d1")

    assert exc_info.value.retryable is False


def test_an_unknown_status_is_refused(server, client):
    server.script = [(200, {"status": "maybe"})]

    with pytest.raises(OrchestratorUnavailable) as exc_info:
        client.cordon("d1")

    assert exc_info.value.retryable is False
    assert "maybe" in str(exc_info.value)


# ---------------------------------------------------------------------- From the settings


def test_there_is_no_client_without_an_address_or_a_key():
    assert OrchestratorClient.from_settings(Settings.from_env({})) is None
    assert OrchestratorClient.from_settings(Settings.from_env({"NODE_MANAGER_NODE_KEY": KEY})) is None
    assert (
        OrchestratorClient.from_settings(Settings.from_env({"NODE_MANAGER_ORCHESTRATOR_URL": "https://logos.example"}))
        is None
    )


def test_an_address_that_is_not_http_is_refused(caplog):
    settings = Settings.from_env({"NODE_MANAGER_ORCHESTRATOR_URL": "file:///etc/passwd", "NODE_MANAGER_NODE_KEY": KEY})

    with caplog.at_level(logging.WARNING):
        assert OrchestratorClient.from_settings(settings) is None

    assert "not an http(s) address" in caplog.text
    assert KEY not in caplog.text


def test_the_client_takes_the_timeout_of_the_settings():
    settings = Settings.from_env(
        {
            "NODE_MANAGER_ORCHESTRATOR_URL": "https://logos.example",
            "NODE_MANAGER_NODE_KEY": KEY,
            "NODE_MANAGER_ORCHESTRATOR_TIMEOUT_S": "7",
        }
    )

    client = OrchestratorClient.from_settings(settings)

    assert client is not None
    assert client._timeout_s == 7


# ---------------------------------------------------------------------- The report of an ending


def test_a_report_carries_the_details_next_to_the_key_and_the_deployment(server, client):
    server.script = [(200, {"status": "accepted"})]

    client.report("d1", {"tag": "v2", "outcome": "succeeded", "drained_requests": 3})

    request = server.requests[0]
    assert request["path"] == f"{API_PATH}/report"
    assert request["body"] == {
        "shared_key": KEY,
        "deployment_id": "d1",
        "tag": "v2",
        "outcome": "succeeded",
        "drained_requests": 3,
    }


def test_the_details_of_a_report_cannot_replace_the_key_or_the_deployment(server, client):
    server.script = [(200, {"status": "accepted"})]

    client.report("d1", {"shared_key": "other", "deployment_id": "d2"})

    assert server.requests[0]["body"] == {"shared_key": KEY, "deployment_id": "d1"}


def test_a_report_the_orchestrator_cannot_deliver_may_be_repeated(server, client):
    server.script = [(503, {"detail": "The notification could not be delivered"})]

    with pytest.raises(OrchestratorUnavailable) as exc_info:
        client.report("d1", {})

    assert exc_info.value.retryable is True


def test_the_requests_of_a_node_are_the_larger_of_the_two_counts():
    reply = CordonReply(granted=True, in_flight_orchestrator=5, in_flight_worker=4)

    assert reply.in_flight == 5
    assert CordonReply(granted=True, in_flight_orchestrator=0, in_flight_worker=3).in_flight == 3
