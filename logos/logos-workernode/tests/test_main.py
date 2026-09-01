from __future__ import annotations

from datetime import datetime, timezone
from os import environ
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

import logos_worker_node.main as worker_main
from logos_worker_node import config as worker_config
from logos_worker_node.models import AppConfig, DeviceSummary, LaneConfig, OllamaConfig, VllmConfig


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

    # This test exercises the CUDA startup guard. Without pinning the backend
    # it would pick the Metal path when the suite runs on a developer's Mac,
    # instantiate the real MetalMetricsCollector instead of _FakeGpuCollector,
    # and hang in lifespan startup instead of raising.
    monkeypatch.setenv("LOGOS_WORKER_BACKEND", "cuda")
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


class TestResolveWorkerCacheRoot:
    """The cache root must resolve exactly as the lane processes do.

    On a Mac the inherited fallback (ollama models path) does not exist and
    is not creatable, so the Metal handle overrides the resolver. Startup
    validation and the prefetch must use that same override, otherwise they
    check and download a directory the lanes never read.
    """

    @staticmethod
    def _cfg(models_path: str):
        return SimpleNamespace(engines=SimpleNamespace(ollama=OllamaConfig(models_path=models_path)))

    def test_metal_backend_uses_the_macos_fallback(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(worker_main, "is_metal_backend", lambda: True)
        monkeypatch.delenv("LOGOS_WORKER_CACHE_ROOT", raising=False)
        root = worker_main._resolve_worker_cache_root(self._cfg(str(tmp_path / "nonexistent-ollama")))
        assert root == str(Path.home() / "Library" / "Caches" / "logos-workernode")

    def test_metal_backend_keeps_a_writable_models_path(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(worker_main, "is_metal_backend", lambda: True)
        monkeypatch.delenv("LOGOS_WORKER_CACHE_ROOT", raising=False)
        root = worker_main._resolve_worker_cache_root(self._cfg(str(tmp_path)))
        assert root == str(tmp_path)

    def test_env_override_wins_on_every_backend(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(worker_main, "is_metal_backend", lambda: True)
        monkeypatch.setenv("LOGOS_WORKER_CACHE_ROOT", str(tmp_path / "custom"))
        root = worker_main._resolve_worker_cache_root(self._cfg("/nonexistent-ollama"))
        assert root == str(tmp_path / "custom")

    def test_non_metal_keeps_the_inherited_resolver(self, monkeypatch) -> None:
        monkeypatch.setattr(worker_main, "is_metal_backend", lambda: False)
        monkeypatch.delenv("LOGOS_WORKER_CACHE_ROOT", raising=False)
        root = worker_main._resolve_worker_cache_root(self._cfg("/usr/share/ollama/.ollama/models"))
        assert root == "/usr/share/ollama/.ollama/models"


class TestPropagateCachePathToEnv:
    """worker.cache_path is lifted into LOGOS_WORKER_CACHE_ROOT as an
    absolute path.

    The example config ships ``~/logos-workernode-mlx/cache``; the lanes
    expand the same root themselves (vllm_process), so validation and the
    prefetch — which read the lifted env var — must address the identical
    directory. A literal ``~`` would make every model look missing and
    prefetch into a stray ``~`` directory the lanes never read.
    """

    def test_tilde_is_expanded_on_lift(self, monkeypatch) -> None:
        # Pre-seed with the empty string (which the lift treats as unset) so
        # the teardown reliably restores the variable to absent — delenv of an
        # already-absent variable registers no undo, and the lift's write
        # would leak into later tests.
        monkeypatch.setenv("LOGOS_WORKER_CACHE_ROOT", "")
        cfg = SimpleNamespace(worker=SimpleNamespace(cache_path="~/logos-workernode-mlx/cache"))
        worker_config._propagate_cache_path_to_env(cfg)
        assert environ["LOGOS_WORKER_CACHE_ROOT"] == str(Path.home() / "logos-workernode-mlx" / "cache")

    def test_explicit_env_var_still_wins(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("LOGOS_WORKER_CACHE_ROOT", str(tmp_path / "custom"))
        cfg = SimpleNamespace(worker=SimpleNamespace(cache_path="~/ignored"))
        worker_config._propagate_cache_path_to_env(cfg)
        assert environ["LOGOS_WORKER_CACHE_ROOT"] == str(tmp_path / "custom")
