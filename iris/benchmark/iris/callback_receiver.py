"""Receives the status callbacks Pyris normally sends to Artemis.

Pyris answers a chat request immediately with 202 and later posts status updates to
{artemisBaseUrl}/api/iris/internal/pipelines/chat/runs/{runId}/status. This small local
HTTP server takes Artemis' place: it collects the updates per run until the run is
FINISHED or FAILED. Only the Python standard library is used.
"""

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

STATUS_PATH = re.compile(r"^/api/iris/internal/pipelines/chat/runs/([^/]+)/status$")
TERMINAL_STATES = {"FINISHED", "FAILED"}


class _Run:
    def __init__(self, token: str):
        self.token = token
        self.updates: list[dict[str, Any]] = []
        self.done = threading.Event()


class CallbackReceiver:
    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self._runs: dict[str, _Run] = {}
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer((host, port), self._handler_class())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def register(self, run_id: str, token: str) -> None:
        with self._lock:
            self._runs[run_id] = _Run(token)

    def wait(self, run_id: str, timeout: float) -> list[dict[str, Any]]:
        """Waits until the run is FINISHED or FAILED and returns all received updates."""
        run = self._runs[run_id]
        if not run.done.wait(timeout):
            raise TimeoutError(f"no final status from Pyris within {timeout:.0f} s")
        with self._lock:
            return list(self._runs.pop(run_id).updates)

    def _receive(self, run_id: str, authorization: str, update: dict[str, Any]) -> int:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return 404
            if authorization != f"Bearer {run.token}":
                return 401
            run.updates.append(update)
            if update.get("runState") in TERMINAL_STATES:
                run.done.set()
            return 200

    def _handler_class(self):
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                match = STATUS_PATH.match(self.path)
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                if not match:
                    code = 404  # e.g. client commands, which the benchmark does not support
                else:
                    try:
                        update = json.loads(body or b"{}")
                    except json.JSONDecodeError:
                        code = 400
                    else:
                        code = receiver._receive(
                            match.group(1), self.headers.get("Authorization", ""), update
                        )
                self.send_response(code)
                self.end_headers()

            def log_message(self, *args):  # keep the command line output clean
                pass

        return Handler
