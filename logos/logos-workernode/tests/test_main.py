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
from logos_worker_node.models import AppConfig, DeviceSummary, LaneConfig, VllmConfig, WorkerConfig


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


@pytest.mark.asyncio
async def test_auto_calibrate_if_needed_skips_on_metal_backend(tmp_path, monkeypatch) -> None:
    """Calibration measures against nvidia-smi and samples /proc/meminfo,
    neither of which exists on macOS. On the Metal backend the function must
    return before touching the calibration machinery — no operator flag
    required."""
    monkeypatch.setenv("LOGOS_WORKER_BACKEND", "metal")
    monkeypatch.delenv("LOGOS_SKIP_AUTO_CALIBRATION", raising=False)
    cfg = MagicMock()
    with patch.object(worker_main, "auto_calibrate_models") as mock_calibrate:
        await worker_main._auto_calibrate_if_needed(  # noqa: SLF001
            cfg,
            MagicMock(),
            tmp_path,
        )
    mock_calibrate.assert_not_called()


@pytest.mark.asyncio
async def test_auto_calibrate_if_needed_runs_on_cuda_backend(tmp_path, monkeypatch) -> None:
    """On the CUDA backend the platform must not skip calibration: an
    uncalibrated capability model still reaches the (mocked) measurement."""
    monkeypatch.setenv("LOGOS_WORKER_BACKEND", "cuda")
    monkeypatch.delenv("LOGOS_SKIP_AUTO_CALIBRATION", raising=False)
    cfg = MagicMock()
    cfg.logos.capabilities_models = ["Org/Model"]
    cfg.engines = None
    profiles = MagicMock()
    profiles.get_profile.return_value = None  # no profile → uncalibrated
    with patch.object(worker_main, "auto_calibrate_models", return_value={}) as mock_calibrate:
        await worker_main._auto_calibrate_if_needed(  # noqa: SLF001
            cfg,
            profiles,
            tmp_path,
        )
    mock_calibrate.assert_called_once()


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


def _write_gguf_snapshot(hf_home: Path, model: str, filenames: list[str]) -> None:
    """Write *model*'s active snapshot into the HF hub cache layout."""
    repo_dir = hf_home / "hub" / ("models--" + model.replace("/", "--"))
    snapshot = repo_dir / "snapshots" / "abc123"
    snapshot.mkdir(parents=True, exist_ok=True)
    (repo_dir / "refs").mkdir(parents=True, exist_ok=True)
    (repo_dir / "refs" / "main").write_text("abc123")
    for name in filenames:
        (snapshot / name).write_bytes(b"\x00")


def test_download_one_model_plain_named_gguf_cache_filters_to_the_quant(tmp_path, monkeypatch) -> None:
    # Regression: a plain-named repository is not GGUF by name — but when
    # its cached weights prove it is (the incomplete shard below is exactly
    # what the capability check queues for repair), the prefetch must
    # download only the quant the capability check validates, not every
    # quantization the repository ships (the tens-of-gigabytes download this
    # feature exists to avoid).
    _write_gguf_snapshot(tmp_path, "Qwen/Qwen3-8B", ["Qwen3-8B-Q4_K_M-00001-of-00002.gguf"])

    calls: list[dict] = []

    def fake(**kwargs) -> None:
        calls.append(kwargs)

    monkeypatch.setattr("huggingface_hub.snapshot_download", fake)
    monkeypatch.delenv("HF_TOKEN", raising=False)

    worker_main._download_one_model("Qwen/Qwen3-8B", str(tmp_path))

    assert len(calls) == 1
    kwargs = calls[0]
    assert kwargs["repo_id"] == "Qwen/Qwen3-8B"
    assert kwargs.get("allow_patterns") is not None
    # The quant the capability check validates (Q4_K_M), nothing else.
    assert all("q4_k_m" in pattern.lower() for pattern in kwargs["allow_patterns"])


def test_download_one_model_plain_named_gguf_cache_respects_lowercase_pin(tmp_path, monkeypatch) -> None:
    # The operator pin is case-insensitive — resolve_gguf_spec uppercases it
    # — so a lowercase pin on a plain-named cached GGUF repo must select the
    # canonical quant the lane serves, not fall back to the full repository.
    _write_gguf_snapshot(tmp_path, "Qwen/Qwen3-8B", ["Qwen3-8B-Q4_K_M-00001-of-00002.gguf"])

    calls: list[dict] = []

    def fake(**kwargs) -> None:
        calls.append(kwargs)

    monkeypatch.setattr("huggingface_hub.snapshot_download", fake)
    monkeypatch.delenv("HF_TOKEN", raising=False)

    worker_main._download_one_model("Qwen/Qwen3-8B", str(tmp_path), "q8_0")

    assert len(calls) == 1
    kwargs = calls[0]
    assert kwargs["repo_id"] == "Qwen/Qwen3-8B"
    assert kwargs.get("allow_patterns") is not None
    assert all("q8_0" in pattern.lower() for pattern in kwargs["allow_patterns"])
    assert all("q4_k_m" not in pattern.lower() for pattern in kwargs["allow_patterns"])


def test_download_one_model_plain_named_without_gguf_cache_downloads_full_repo(tmp_path, monkeypatch) -> None:
    # No cached GGUF evidence → a plain-named repository keeps the
    # full-repository download (no allow_patterns filtering).
    calls: list[dict] = []

    def fake(**kwargs) -> None:
        calls.append(kwargs)

    monkeypatch.setattr("huggingface_hub.snapshot_download", fake)
    monkeypatch.delenv("HF_TOKEN", raising=False)

    worker_main._download_one_model("Qwen/Qwen3-8B", str(tmp_path))

    assert len(calls) == 1
    assert "allow_patterns" not in calls[0]


def test_download_one_model_skips_local_file_refs(tmp_path, monkeypatch) -> None:
    # Regression: local GGUF file references (absolute AND relative) point at
    # the host filesystem, not a Hub repository — the prefetch must not
    # attempt to download them (the relative form used to fall through to
    # snapshot_download(repo_id="./models")).
    pytest.importorskip("huggingface_hub")

    def _no_download(**kwargs) -> None:
        raise AssertionError(f"local reference must not be downloaded: {kwargs}")

    monkeypatch.setattr("huggingface_hub.snapshot_download", _no_download)

    # Absolute local file …
    worker_main._download_one_model(str(tmp_path / "models" / "model.gguf"), str(tmp_path))
    # … relative local file (resolved against the working directory) …
    monkeypatch.chdir(tmp_path)
    worker_main._download_one_model("./models/model.gguf", str(tmp_path))
    # … and the local directory reference, as before.
    worker_main._download_one_model(f"{tmp_path}/qwen-GGUF:Q4_K_M", str(tmp_path))


def test_startup_hf_home_blank_env_falls_back_to_the_cache_root(tmp_path, monkeypatch) -> None:
    # Regression: a blank/whitespace HF_HOME must fall back to
    # <cache_root>/.hf_cache — the directory the startup prefetch populates
    # and capability validation checks — instead of resolving to a relative
    # "hub" path under the working directory that ignores cached weights.
    cache_root = str(tmp_path / "models")
    fallback = str(tmp_path / "models" / ".hf_cache")

    monkeypatch.setenv("HF_HOME", "")
    assert worker_main._startup_hf_home(cache_root) == fallback
    monkeypatch.setenv("HF_HOME", "   ")
    assert worker_main._startup_hf_home(cache_root) == fallback
    monkeypatch.delenv("HF_HOME")
    assert worker_main._startup_hf_home(cache_root) == fallback
    # A real value still wins.
    monkeypatch.setenv("HF_HOME", "/explicit/hf")
    assert worker_main._startup_hf_home(cache_root) == "/explicit/hf"
