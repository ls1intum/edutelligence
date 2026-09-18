"""Fake ProcessHandle for the per-request overhead benchmark.

Represents a **warm** vLLM lane: the "backend process" is the mock lane
(``mock_lane.py``) listening on ``port``. The handle reports the process as
RUNNING with ``pid=None`` — which makes the LaneManager skip the nvidia-smi
VRAM query and the /proc host-RAM walk (no GPU in CI; documented
under-estimation, see README).

The liveness probes the LaneManager performs while building a lane status
(``get_loaded_models``, ``get_backend_metrics``, ``is_sleeping``) are **real
HTTP calls against the mock lane**, so the status-build cost measured by the
benchmark is the same order of magnitude as in production.

This is exactly the injection pattern used by the worker's own unit tests
(``manager._handles[lane_id] = FakeHandle()``).
"""

from __future__ import annotations

from typing import Any, AsyncIterator

import httpx

from logos_worker_node.models import LaneConfig, ProcessState, ProcessStatus

_PROCESS_TIMEOUT = 5.0


def _metrics_text_to_dict(text: str) -> dict[str, Any]:
    """Minimal Prometheus-text parser for the two counters the mock lane serves.

    Mirrors the key set of ``VllmProcessHandle.get_backend_metrics`` so the
    status payload shapes match production; only the counters the mock
    exposes are filled in, the rest stay None.
    """
    out: dict[str, Any] = {
        "engine": "vllm",
        "queue_waiting": None,
        "requests_running": None,
        "gpu_cache_usage_percent": None,
        "prefix_cache_hit_rate": None,
        "mtp_acceptance_rate": None,
        "mtp_draft_tokens_total": None,
        "mtp_accepted_tokens_total": None,
        "prompt_tokens_total": None,
        "generation_tokens_total": None,
        "ttft_histogram": {},
        "tpot_histogram": {},
        "e2e_latency_histogram": {},
        "last_prefill_s": None,
        "last_prefill_tokens": None,
    }
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.rsplit(" ", 1)
        if len(parts) != 2:
            continue
        name, raw = parts
        try:
            value = float(raw)
        except ValueError:
            continue
        if name == "vllm:prompt_tokens_total":
            out["prompt_tokens_total"] = int(value)
        elif name == "vllm:generation_tokens_total":
            out["generation_tokens_total"] = int(value)
        elif name == "vllm:num_requests_running":
            out["requests_running"] = int(value)
    return out


class FakeLaneHandle:
    """ProcessHandle for a mock-lane-backed warm lane (see module docstring)."""

    def __init__(self, lane_id: str, port: int, lane_config: LaneConfig) -> None:
        self.lane_id = lane_id
        self.port = port
        self.lane_config = lane_config

    # -- Process lifecycle ------------------------------------------------

    @property
    def config(self) -> LaneConfig:
        return self.lane_config

    def status(self) -> ProcessStatus:
        # Warm: process up, no real pid (skips VRAM//proc measurement paths).
        return ProcessStatus(state=ProcessState.RUNNING, pid=None)

    async def init(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def spawn(self, lane_config: LaneConfig) -> ProcessStatus:
        return self.status()

    async def stop(self) -> ProcessStatus:
        return ProcessStatus(state=ProcessState.STOPPED, pid=None)

    async def reconfigure(self, lane_config: LaneConfig) -> ProcessStatus:
        return self.status()

    async def destroy(self) -> None:
        return None

    # -- Model operations (unused by the benchmark path; no-ops) -----------

    async def preload_model(self, model_name: str) -> bool:
        return True

    async def unload_model(self, model_name: str) -> bool:
        return True

    async def pull_model(self, model_name: str) -> bool:
        return True

    async def delete_model(self, model_name: str) -> bool:
        return True

    async def create_model(self, name: str, modelfile: str) -> bool:
        return True

    async def copy_model(self, source: str, destination: str) -> bool:
        return True

    async def show_model(self, model_name: str) -> dict[str, Any] | None:
        return None

    async def pull_model_streaming(self, model_name: str) -> AsyncIterator[dict[str, Any]]:
        if False:
            yield {}

    async def get_available_models(self) -> list[dict[str, Any]]:
        return []

    async def get_version(self) -> str | None:
        return "bench-mock"

    # -- Status probes (REAL HTTP against the mock lane) --------------------

    async def get_loaded_models(self) -> list[dict[str, Any]]:
        base = f"http://127.0.0.1:{self.port}"
        async with httpx.AsyncClient(timeout=_PROCESS_TIMEOUT) as client:
            resp = await client.get(f"{base}/v1/models")
            resp.raise_for_status()
            data = resp.json().get("data", [])
        return [{"name": item.get("id", ""), "size": 0, "size_vram": 0} for item in data]

    async def get_backend_metrics(self) -> dict[str, Any]:
        base = f"http://127.0.0.1:{self.port}"
        async with httpx.AsyncClient(timeout=_PROCESS_TIMEOUT) as client:
            resp = await client.get(f"{base}/metrics")
            resp.raise_for_status()
        return _metrics_text_to_dict(resp.text)

    async def is_sleeping(self) -> bool | None:
        base = f"http://127.0.0.1:{self.port}"
        async with httpx.AsyncClient(timeout=_PROCESS_TIMEOUT) as client:
            resp = await client.get(f"{base}/is_sleeping")
            resp.raise_for_status()
            return bool(resp.json().get("is_sleeping", False))

    # -- Sleep/wake (never exercised on the warm-lane benchmark path) -------

    async def sleep(self, level: int = 1, mode: str = "wait") -> dict[str, Any]:
        return {}

    async def wake_up(self) -> dict[str, Any]:
        return {}
