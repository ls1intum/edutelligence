from __future__ import annotations

from datetime import datetime, timezone
from os import environ
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI

import logos_worker_node.main as worker_main
from logos_worker_node import config as worker_config
from logos_worker_node.models import AppConfig, DeviceSummary, LaneConfig, LogosConfig, VllmConfig, WorkerConfig


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

    # This test exercises the CUDA startup guard. Without pinning the application server
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
        patch.object(worker_main, "cached_vllm_version", return_value=""),
        patch("logos_worker_node.main.create_model_cache", return_value=mock_cache),
        patch.dict("sys.modules", {"logos_worker_node.flashinfer_warmup": MagicMock()}),
    ):
        context = worker_main.lifespan(app)

        with pytest.raises(RuntimeError, match="nvidia-smi"):
            await context.__aenter__()


@pytest.mark.asyncio
async def test_lifespan_bootstraps_central_hf_token_before_startup_model_operations(
    tmp_path,
    monkeypatch,
) -> None:
    cfg = AppConfig(
        logos=LogosConfig(
            enabled=True,
            logos_url="https://logos.example:8080",
            shared_key="secret",
        ),
        lanes=[
            LaneConfig(
                lane_id="qwen-vllm",
                model="Qwen/Qwen3-8B",
                vllm=True,
                vllm_config=VllmConfig(),
            )
        ],
    )

    mock_cache = MagicMock()
    mock_cache.enabled = False

    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setenv("LOGOS_WORKER_BACKEND", "cuda")
    monkeypatch.setattr(worker_main, "load_config", lambda: cfg)
    monkeypatch.setattr(worker_main, "get_state_dir", lambda: tmp_path)
    monkeypatch.setattr(worker_main, "GpuMetricsCollector", _FakeGpuCollector)

    class _Resp:
        status_code = 200
        content = b"{}"

        @staticmethod
        def json():
            return {"ws_url": "wss://logos.example/ws", "hf_token": "central-token", "profiles": {}}

    class _HttpClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):  # noqa: ARG002
            return None

        async def post(self, url: str, json=None):  # noqa: ARG002
            return _Resp()

    app = FastAPI()
    with (
        patch.object(worker_main, "cached_vllm_version", return_value=""),
        patch("logos_worker_node.main.create_model_cache", return_value=mock_cache),
        patch.dict("sys.modules", {"logos_worker_node.flashinfer_warmup": MagicMock()}),
        patch(
            "logos_worker_node.logos_bridge.httpx.AsyncClient",
            lambda timeout=15.0: _HttpClient(),
        ),
    ):
        context = worker_main.lifespan(app)

        with pytest.raises(RuntimeError, match="nvidia-smi"):
            await context.__aenter__()

    assert environ["HF_TOKEN"] == "central-token"


class TestResolveWorkerCacheRoot:
    """The cache root must resolve exactly as the lane processes do.

    On a Mac the inherited fallback (worker models path) does not exist and
    is not creatable, so the Metal handle overrides the resolver. Startup
    validation and the prefetch must use that same override, otherwise they
    check and download a directory the lanes never read.
    """

    @staticmethod
    def _cfg(models_path: str):
        return SimpleNamespace(worker=WorkerConfig(models_path=models_path))

    def test_metal_backend_uses_the_macos_fallback(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(worker_main, "is_metal_backend", lambda: True)
        monkeypatch.delenv("LOGOS_WORKER_CACHE_ROOT", raising=False)
        root = worker_main._resolve_worker_cache_root(self._cfg(str(tmp_path / "nonexistent-models")))
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
        root = worker_main._resolve_worker_cache_root(self._cfg("/usr/share/logos/models"))
        assert root == "/usr/share/logos/models"


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


class _FakeBridge:
    def __init__(self, failures: int, profiles: dict) -> None:
        self.failures = failures
        self.profiles = profiles
        self.calls: list = []

    async def fetch_model_profiles(self, key_hashes, legacy_import):
        self.calls.append((key_hashes, legacy_import))
        if len(self.calls) <= self.failures:
            raise RuntimeError("Logos unreachable")
        return self.profiles


def _central_cfg(enabled: bool) -> AppConfig:
    return AppConfig(
        logos=LogosConfig(
            enabled=enabled,
            logos_url="https://logos.example:8080",
            shared_key="secret",
            capabilities_models=["org/model"],
        )
    )


@pytest.mark.asyncio
async def test_central_profiles_wait_for_logos_and_hand_over_the_legacy_files(tmp_path, monkeypatch) -> None:
    """No lane may start without profiles: the worker retries until Logos
    answers, then hands its old profile file over exactly once."""
    from logos_worker_node.model_profiles import ModelProfileRegistry

    (tmp_path / "model_profiles.yml").write_text("model_profiles:\n  org/model:\n    base_residency_mb: 5.0\n")
    sleeps: list = []

    async def _sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setenv("LOGOS_WORKER_BACKEND", "cuda")
    monkeypatch.setattr(worker_main, "get_state_dir", lambda: tmp_path)
    monkeypatch.setattr(worker_main, "cached_vllm_version", lambda binary: "0.30.0")
    monkeypatch.setattr(worker_main.asyncio, "sleep", _sleep)
    bridge = _FakeBridge(failures=2, profiles={"org/model": {"base_residency_mb": 7.0, "sync_revision": 3}})
    registry = ModelProfileRegistry()

    await worker_main._load_central_profiles(_central_cfg(True), bridge, registry, _FakeGpuCollector(1))  # noqa: SLF001

    assert sleeps == [5.0, 10.0]
    key_hashes, legacy = bridge.calls[0]
    assert set(key_hashes) == {"org/model"}
    assert legacy == {"model_profiles": {"org/model": {"base_residency_mb": 5.0}}, "unsupported_models": {}}
    profile = registry.get_profile("org/model")
    assert (profile.base_residency_mb, profile.sync_revision) == (7.0, 3)
    assert not (tmp_path / "model_profiles.yml").exists()
    assert (tmp_path / "model_profiles.yml.migrated").exists()


@pytest.mark.asyncio
async def test_central_profiles_skip_logos_when_the_bridge_is_disabled(tmp_path, monkeypatch) -> None:
    from logos_worker_node.model_profiles import ModelProfileRegistry

    monkeypatch.setenv("LOGOS_WORKER_BACKEND", "cuda")
    monkeypatch.setattr(worker_main, "get_state_dir", lambda: tmp_path)
    monkeypatch.setattr(worker_main, "cached_vllm_version", lambda binary: "")
    bridge = _FakeBridge(failures=0, profiles={})
    registry = ModelProfileRegistry()

    await worker_main._load_central_profiles(
        _central_cfg(False), bridge, registry, _FakeGpuCollector(1)
    )  # noqa: SLF001

    assert bridge.calls == []
    assert set(registry.calibration_key_hashes()) == {"org/model"}
