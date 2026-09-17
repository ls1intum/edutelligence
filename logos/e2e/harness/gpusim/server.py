"""Fake vLLM OpenAI server.

Implements the surface ``VllmProcessHandle`` actually talks to — ``/health``,
``/version``, ``/v1/models``, ``/v1/completions``, ``/v1/chat/completions``,
``/metrics``, ``/sleep``, ``/wake_up``, ``/is_sleeping``, ``/reset_mm_cache`` —
and nothing else.

Deliberately stdlib-only: this runs as a subprocess spawned by the worker under
whatever ``python3`` is first on PATH, which is not necessarily the interpreter
the test suite installed its dependencies into.

VRAM is real here in the only sense that matters to the code under test: the
server debits its allocation from the shared simulator state on startup and
credits it back on a clean shutdown, so ``nvidia-smi --query-compute-apps``
reports it exactly the way ``_verify_vram_released`` expects.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from harness.gpusim import state as gpustate
from harness.gpusim.scenario import VllmScript

#: Version the fake reports at ``/version``. Kept close to what the worker
#: images pin so version-gated branches take their production path.
FAKE_VLLM_VERSION = "0.11.0"

#: Canned completion text. Short and deterministic so streaming tests can
#: assert on exact chunk counts.
COMPLETION_TEXT = "Simulated response from the Logos E2E vLLM stub."


class Lane:
    """Mutable serving state for the one model this process hosts."""

    def __init__(self, model: str, script: VllmScript, vram_mb: float) -> None:
        self.model = model
        self.script = script
        self.vram_mb = vram_mb
        self.started_at = time.time()
        self.sleeping = False
        self.requests_total = 0
        self.prompt_tokens_total = 0
        self.generation_tokens_total = 0

    @property
    def ready(self) -> bool:
        return time.time() - self.started_at >= self.script.ready_after_s


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    lane: Lane  # injected on the server instance, see run()

    protocol_version = "HTTP/1.1"

    # Silence per-request logging; the worker streams our stdout into its own
    # log and access lines would drown the startup banner tests assert on.
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        pass

    # -- helpers ----------------------------------------------------------

    def _send(self, status: int, payload: Any = None, *, content_type: str = "application/json") -> None:
        body = b"" if payload is None else _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _send_text(self, status: int, text: str, content_type: str = "text/plain") -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    # -- routes -----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        lane = self.server.lane  # type: ignore[attr-defined]

        if path == "/health":
            self._send(200 if lane.ready else 503)
        elif path == "/version":
            self._send(200, {"version": FAKE_VLLM_VERSION})
        elif path == "/v1/models":
            self._send(200, self._models_payload(lane))
        elif path == "/metrics":
            self._send_text(200, self._metrics_text(lane))
        elif path == "/is_sleeping":
            if lane.script.wedge_engine_core:
                # The API server is alive but its EngineCore RPC never answers.
                # Block forever: the worker's own timeout is what must fire.
                while True:
                    time.sleep(3600)
            self._send(200, {"is_sleeping": lane.sleeping})
        else:
            self._send(404, {"error": {"message": f"Unknown route {path}", "type": "not_found"}})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        query = parse_qs(urlparse(self.path).query)
        lane = self.server.lane  # type: ignore[attr-defined]

        if path == "/sleep":
            if lane.script.refuse_sleep:
                self._send(500, {"error": "Sleep mode is not enabled for this engine"})
                return
            lane.sleeping = True
            level = int((query.get("level") or ["1"])[0])
            self._send(200, {"is_sleeping": True, "level": level})
        elif path == "/wake_up":
            if lane.script.slow_wake_s:
                time.sleep(lane.script.slow_wake_s)
            lane.sleeping = False
            self._send(200, {"is_sleeping": False})
        elif path == "/reset_mm_cache":
            self._send(200, {})
        elif path in ("/v1/chat/completions", "/v1/completions"):
            self._completion(lane, path, self._read_json())
        else:
            self._send(404, {"error": {"message": f"Unknown route {path}", "type": "not_found"}})

    # -- payloads ---------------------------------------------------------

    @staticmethod
    def _models_payload(lane: Lane) -> dict[str, Any]:
        return {
            "object": "list",
            "data": [
                {
                    "id": lane.model,
                    "object": "model",
                    "created": int(lane.started_at),
                    "owned_by": "vllm",
                    "root": lane.model,
                    "max_model_len": 32768,
                }
            ],
        }

    def _completion(self, lane: Lane, path: str, body: dict[str, Any]) -> None:
        if lane.sleeping:
            self._send(503, {"error": {"message": "engine is sleeping", "type": "service_unavailable"}})
            return

        lane.requests_total += 1
        prompt_tokens = 16
        words = COMPLETION_TEXT.split()
        lane.prompt_tokens_total += prompt_tokens
        lane.generation_tokens_total += len(words)

        chat = path.endswith("/chat/completions")
        request_id = f"cmpl-{uuid.uuid4().hex[:24]}"
        created = int(time.time())
        model = body.get("model") or lane.model

        if not body.get("stream"):
            self._send(200, self._final_payload(chat, request_id, created, model, prompt_tokens, words))
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            for index, word in enumerate(words):
                chunk = self._stream_chunk(chat, request_id, created, model, word, first=index == 0)
                self.wfile.write(b"data: " + _json_bytes(chunk) + b"\n\n")
                self.wfile.flush()
            self.wfile.write(b"data: " + _json_bytes(self._stream_stop(chat, request_id, created, model)) + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            # The client hung up mid-stream. That is a scenario under test, not
            # an error here — let the connection die quietly.
            return

    @staticmethod
    def _final_payload(
        chat: bool, request_id: str, created: int, model: str, prompt_tokens: int, words: list[str]
    ) -> dict[str, Any]:
        text = " ".join(words)
        choice = (
            {"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
            if chat
            else {"index": 0, "text": text, "finish_reason": "stop"}
        )
        return {
            "id": request_id,
            "object": "chat.completion" if chat else "text_completion",
            "created": created,
            "model": model,
            "choices": [choice],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": len(words),
                "total_tokens": prompt_tokens + len(words),
                "prompt_tokens_details": {"cached_tokens": 0},
            },
        }

    @staticmethod
    def _stream_chunk(chat: bool, request_id: str, created: int, model: str, word: str, first: bool) -> dict[str, Any]:
        piece = word if first else f" {word}"
        delta: dict[str, Any] = {"content": piece}
        if first and chat:
            delta["role"] = "assistant"
        choice = (
            {"index": 0, "delta": delta, "finish_reason": None}
            if chat
            else {"index": 0, "text": piece, "finish_reason": None}
        )
        return {
            "id": request_id,
            "object": "chat.completion.chunk" if chat else "text_completion",
            "created": created,
            "model": model,
            "choices": [choice],
        }

    @staticmethod
    def _stream_stop(chat: bool, request_id: str, created: int, model: str) -> dict[str, Any]:
        choice = (
            {"index": 0, "delta": {}, "finish_reason": "stop"}
            if chat
            else {"index": 0, "text": "", "finish_reason": "stop"}
        )
        return {
            "id": request_id,
            "object": "chat.completion.chunk" if chat else "text_completion",
            "created": created,
            "model": model,
            "choices": [choice],
        }

    @staticmethod
    def _metrics_text(lane: Lane) -> str:
        """Prometheus exposition using vLLM's real metric names.

        Only the series ``get_backend_metrics`` parses are emitted; anything
        else would be dead weight the worker skips anyway.
        """
        labels = f'{{model_name="{lane.model}"}}'
        ttft_count = max(lane.requests_total, 0)
        lines = [
            "# TYPE vllm:num_requests_waiting gauge",
            f"vllm:num_requests_waiting{labels} 0.0",
            "# TYPE vllm:num_requests_running gauge",
            f"vllm:num_requests_running{labels} 0.0",
            "# TYPE vllm:gpu_cache_usage_perc gauge",
            f"vllm:gpu_cache_usage_perc{labels} 0.12",
            "# TYPE vllm:gpu_prefix_cache_queries_total counter",
            f"vllm:gpu_prefix_cache_queries_total{labels} {float(ttft_count * 16):.1f}",
            "# TYPE vllm:gpu_prefix_cache_hits_total counter",
            f"vllm:gpu_prefix_cache_hits_total{labels} {float(ttft_count * 4):.1f}",
            "# TYPE vllm:prompt_tokens_total counter",
            f"vllm:prompt_tokens_total{labels} {float(lane.prompt_tokens_total):.1f}",
            "# TYPE vllm:generation_tokens_total counter",
            f"vllm:generation_tokens_total{labels} {float(lane.generation_tokens_total):.1f}",
            "# TYPE vllm:time_to_first_token_seconds histogram",
            f'vllm:time_to_first_token_seconds_bucket{{model_name="{lane.model}",le="0.1"}} {float(ttft_count):.1f}',
            f'vllm:time_to_first_token_seconds_bucket{{model_name="{lane.model}",le="+Inf"}} {float(ttft_count):.1f}',
            f"vllm:time_to_first_token_seconds_sum{labels} {ttft_count * 0.08:.4f}",
            f"vllm:time_to_first_token_seconds_count{labels} {float(ttft_count):.1f}",
            "# TYPE vllm:time_per_output_token_seconds histogram",
            f'vllm:time_per_output_token_seconds_bucket{{model_name="{lane.model}",le="+Inf"}} {float(ttft_count):.1f}',
            f"vllm:time_per_output_token_seconds_sum{labels} {ttft_count * 0.01:.4f}",
            f"vllm:time_per_output_token_seconds_count{labels} {float(ttft_count):.1f}",
            "# TYPE vllm:e2e_request_latency_seconds histogram",
            f'vllm:e2e_request_latency_seconds_bucket{{model_name="{lane.model}",le="+Inf"}} {float(ttft_count):.1f}',
        ]
        return "\n".join(lines) + "\n"


def _startup_banner(lane: Lane, port: int) -> str:
    """Lines the worker parses out of the startup log.

    ``Maximum concurrency …`` feeds ``VllmProcessHandle.max_concurrency`` and
    calibration's served-context extraction, so its shape has to match
    ``_VLLM_MAX_CONCURRENCY_RE`` exactly.
    """
    lines = [
        f"INFO [api_server.py:1000] vLLM API server version {FAKE_VLLM_VERSION}",
        f"INFO [core.py:200] Loading model {lane.model}...",
        f"INFO [kv_cache_utils.py:900] Maximum concurrency for "
        f"{lane.script.max_concurrency_tokens:,} tokens per request: {lane.script.max_concurrency:.2f}x",
        f"INFO [api_server.py:1600] Starting vLLM API server on http://0.0.0.0:{port}",
    ]
    if lane.script.emit_dev_mode_warning:
        lines.insert(0, "WARNING [api_server.py:100] SECURITY WARNING: Development endpoints are enabled")
    return "\n".join(lines)


def run(model: str, port: int, script: VllmScript, vram_by_device: dict[int, float]) -> int:
    """Serve until SIGTERM, holding each device's own allocation in the simulator.

    Keyed per device because a mixed-architecture tensor-parallel lane claims a
    different amount on each card; one figure for the whole lane would book the
    first GPU's share against all of them.
    """
    lane = Lane(model=model, script=script, vram_mb=sum(vram_by_device.values()))
    pid = os.getpid()

    # Bind before claiming VRAM. Binding is the step that can still fail (a port
    # collision — `lane.free_port()` hands out a port it has already closed), and
    # an allocation recorded before it would never be released: the simulator
    # would carry a phantom allocation for a process that never ran, and every
    # later capacity assertion in that session would be measured against it.
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    server.lane = lane  # type: ignore[attr-defined]
    server.daemon_threads = True

    claimed = {index: mb for index, mb in vram_by_device.items() if mb > 0}
    if claimed:
        with gpustate.mutate() as sim:
            for index, mb in claimed.items():
                sim.allocate(pid, index, mb)

    print(_startup_banner(lane, port), flush=True)

    stopping = threading.Event()

    def _release() -> None:
        if not claimed:
            return
        try:
            with gpustate.mutate() as sim:
                if script.leak_vram:
                    # The process is going away but the driver never reclaims
                    # the context — the stuck-VRAM signature.
                    sim.mark_leaked(pid)
                else:
                    sim.release(pid)
        except gpustate.GpuSimStateError:
            pass

    def _on_signal(signum: int, _frame: Any) -> None:
        if stopping.is_set():
            return
        stopping.set()
        print(f"INFO [api_server.py:1700] Received signal {signum}, shutting down", flush=True)
        _release()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        if not stopping.is_set():
            _release()
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via bin/vllm
    sys.exit(
        run(
            model=sys.argv[1],
            port=int(sys.argv[2]),
            script=VllmScript.read(),
            vram_by_device={0: float(sys.argv[3])},
        )
    )
