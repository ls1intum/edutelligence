from __future__ import annotations

import pytest
from fastapi import FastAPI

import logos_worker_node.main as worker_main
from logos_worker_node.models import AppConfig, LaneConfig, VllmConfig


class _FakeGpuCollector:
    def __init__(self, poll_interval: int) -> None:  # noqa: ARG002
        self.available = False
        self.stopped = False

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        self.stopped = True


@pytest.mark.asyncio
async def test_lifespan_fails_startup_when_vllm_configured_without_nvidia_smi(monkeypatch) -> None:
    cfg = AppConfig(
        lanes=[
            LaneConfig(
                lane_id="qwen-vllm",
                model="Qwen/Qwen3-8B",
                vllm=True,
                vllm_config=VllmConfig(),
            )
        ]
    )

    monkeypatch.setattr(worker_main, "load_config", lambda: cfg)
    monkeypatch.setattr(worker_main, "GpuMetricsCollector", _FakeGpuCollector)

    app = FastAPI()
    context = worker_main.lifespan(app)

    with pytest.raises(RuntimeError, match="nvidia-smi"):
        await context.__aenter__()
