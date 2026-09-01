from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

import logos_worker_node.main as worker_main
from logos_worker_node.models import AppConfig, DeviceSummary, LaneConfig, VllmConfig


class _FakeGpuCollector:
    def __init__(self, poll_interval: int) -> None:  # noqa: ARG002
        self.available = False
        self.device_count = 0
        self.per_gpu_vram_mb = 0.0
        self.stopped = False

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        self.stopped = True

    async def force_poll(self) -> None:
        return None

    async def get_snapshot(self) -> DeviceSummary:
        return DeviceSummary(
            timestamp=datetime.now(timezone.utc),
            mode="none",
            nvidia_smi_available=False,
        )


@pytest.mark.asyncio
async def test_lifespan_fails_startup_when_vllm_configured_without_nvidia_smi(
    tmp_path,
    monkeypatch,
) -> None:
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

    mock_cache = MagicMock()
    mock_cache.enabled = False

    monkeypatch.setattr(worker_main, "load_config", lambda: cfg)
    # get_state_dir must return a real Path now — gpu_watchdog uses it to
    # persist its rate-limit marker file at lifespan startup.
    monkeypatch.setattr(worker_main, "get_state_dir", lambda: tmp_path)
    monkeypatch.setattr(worker_main, "GpuMetricsCollector", _FakeGpuCollector)

    app = FastAPI()
    with (
        patch.object(worker_main, "_auto_calibrate_if_needed", new_callable=AsyncMock),
        patch("logos_worker_node.main.create_model_cache", return_value=mock_cache),
        patch.dict("sys.modules", {"logos_worker_node.flashinfer_warmup": MagicMock()}),
    ):
        context = worker_main.lifespan(app)

        with pytest.raises(RuntimeError, match="nvidia-smi"):
            await context.__aenter__()


def test_download_one_model_explicit_quant_beats_operator_pin(tmp_path, monkeypatch) -> None:
    # Regression: an explicit repo:quant reference must prefetch the quant it
    # names. resolve_gguf_spec serves the embedded quant and ignores any
    # operator pin, so the prefetch has to download the same one — otherwise
    # the lane boots against a quant that was never fetched.
    calls: list[dict] = []

    def fake(**kwargs) -> None:
        calls.append(kwargs)

    monkeypatch.setattr("huggingface_hub.snapshot_download", fake)
    monkeypatch.delenv("HF_TOKEN", raising=False)

    worker_main._download_one_model("unsloth/Qwen3-8B-GGUF:Q8_0", str(tmp_path), "Q4_K_M")

    assert len(calls) == 1
    kwargs = calls[0]
    assert kwargs["repo_id"] == "unsloth/Qwen3-8B-GGUF"
    assert kwargs["allow_patterns"] is not None
    # The embedded quant (Q8_0), not the operator pin (Q4_K_M), is downloaded.
    assert all("q8_0" in pattern.lower() for pattern in kwargs["allow_patterns"])
    assert all("q4_k_m" not in pattern.lower() for pattern in kwargs["allow_patterns"])
