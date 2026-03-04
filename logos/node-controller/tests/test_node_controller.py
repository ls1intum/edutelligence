"""
Unit tests for the Node Controller.

Tests cover: config loading/saving, GPU parsing, Ollama manager (mocked Docker),
auth, and API endpoints.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestConfig:
    """Tests for config loading, saving, and reconfigure."""

    def test_load_defaults_when_no_file(self):
        """Loading with no file should return defaults."""
        from node_controller.config import load_config
        from node_controller.models import AppConfig

        with tempfile.TemporaryDirectory() as d:
            # cd to empty dir so no config.yml is found
            import os

            old = os.getcwd()
            try:
                os.chdir(d)
                cfg = load_config()
                assert isinstance(cfg, AppConfig)
                assert cfg.ollama.num_parallel == 4
                assert cfg.controller.port == 8443
            finally:
                os.chdir(old)

    def test_load_from_file(self, tmp_path: Path):
        """Loading from a valid YAML file should parse correctly."""
        from node_controller.config import load_config

        config_data = {
            "controller": {"port": 9999, "api_key": "test-key"},
            "ollama": {
                "num_parallel": 8,
                "image": "ollama/ollama:0.5",
                "container_name": "my-ollama",
            },
        }
        config_file = tmp_path / "config.yml"
        config_file.write_text(yaml.dump(config_data))

        cfg = load_config(config_file)
        assert cfg.controller.port == 9999
        assert cfg.controller.api_key == "test-key"
        assert cfg.ollama.num_parallel == 8
        assert cfg.ollama.image == "ollama/ollama:0.5"
        assert cfg.ollama.container_name == "my-ollama"
        # Defaults preserved for unspecified fields
        assert cfg.ollama.max_loaded_models == 3
        assert cfg.ollama.flash_attention is True

    def test_save_atomic(self, tmp_path: Path):
        """Saving should write a valid YAML file atomically."""
        from node_controller.config import load_config, save_config

        config_file = tmp_path / "config.yml"
        config_file.write_text(yaml.dump({"controller": {"port": 1234}}))

        cfg = load_config(config_file)
        cfg.ollama.num_parallel = 16
        save_config(cfg)

        # Reload and verify
        reloaded = yaml.safe_load(config_file.read_text())
        assert reloaded["ollama"]["num_parallel"] == 16
        assert reloaded["controller"]["port"] == 1234

    def test_apply_reconfigure(self, tmp_path: Path):
        """apply_reconfigure should update fields and detect restart needs."""
        from node_controller.config import apply_reconfigure, load_config

        config_file = tmp_path / "config.yml"
        config_file.write_text(yaml.dump({"ollama": {"num_parallel": 4}}))
        load_config(config_file)

        # Changing num_parallel requires restart
        new_cfg, needs_restart, changed = apply_reconfigure({"num_parallel": 8})
        assert needs_restart is True
        assert new_cfg.num_parallel == 8
        assert changed == ["num_parallel"]

        # Changing preload_models does NOT require restart
        new_cfg2, needs_restart2, changed2 = apply_reconfigure(
            {"preload_models": ["llama3.2"]}
        )
        assert needs_restart2 is False
        assert new_cfg2.preload_models == ["llama3.2"]
        assert changed2 == ["preload_models"]

    def test_apply_reconfigure_no_change(self, tmp_path: Path):
        """No-op reconfigure should not require restart."""
        from node_controller.config import apply_reconfigure, load_config

        config_file = tmp_path / "config.yml"
        config_file.write_text(yaml.dump({"ollama": {"num_parallel": 4}}))
        load_config(config_file)

        _, needs_restart, changed = apply_reconfigure({"num_parallel": 4})
        assert needs_restart is False
        assert changed == []

    def test_apply_reconfigure_reports_only_actual_changes(self, tmp_path: Path):
        """changed list should only include fields whose values differ."""
        from node_controller.config import apply_reconfigure, load_config

        config_file = tmp_path / "config.yml"
        config_file.write_text(yaml.dump({"ollama": {"num_parallel": 4, "keep_alive": "5m"}}))
        load_config(config_file)

        # Submit two fields, but only one actually changes
        _, needs_restart, changed = apply_reconfigure(
            {"num_parallel": 8, "keep_alive": "5m"}
        )
        assert needs_restart is True
        assert changed == ["num_parallel"]
        assert "keep_alive" not in changed


# ---------------------------------------------------------------------------
# GPU collector tests
# ---------------------------------------------------------------------------


class TestGpuCollector:
    """Tests for nvidia-smi parsing."""

    @pytest.mark.asyncio
    async def test_parse_nvidia_smi_output(self):
        """Verify parsing of nvidia-smi CSV output."""
        from node_controller.gpu import GpuMetricsCollector

        collector = GpuMetricsCollector(poll_interval=60)
        csv_output = (
            "0, GPU-abc-123, NVIDIA A100-SXM4-80GB, 12345, 81920, 45, 62, 250.00\n"
            "1, GPU-def-456, NVIDIA A100-SXM4-80GB, 8192, 81920, 30, 55, [N/A]\n"
        )

        with patch.object(collector, "_run_nvidia_smi", return_value=csv_output):
            await collector._poll()

        snapshot = await collector.get_snapshot()
        assert len(snapshot.gpus) == 2

        gpu0 = snapshot.gpus[0]
        assert gpu0.index == 0
        assert gpu0.name == "NVIDIA A100-SXM4-80GB"
        assert gpu0.memory_used_mb == 12345.0
        assert gpu0.memory_total_mb == 81920.0
        assert gpu0.memory_free_mb == 81920.0 - 12345.0
        assert gpu0.utilization_percent == 45.0
        assert gpu0.temperature_celsius == 62.0
        assert gpu0.power_draw_watts == 250.0

        gpu1 = snapshot.gpus[1]
        assert gpu1.power_draw_watts is None  # [N/A]

        assert snapshot.total_vram_mb == 81920.0 * 2
        assert snapshot.used_vram_mb == 12345.0 + 8192.0

    @pytest.mark.asyncio
    async def test_handles_missing_nvidia_smi(self):
        """Should degrade gracefully when nvidia-smi is not found."""
        from node_controller.gpu import GpuMetricsCollector

        collector = GpuMetricsCollector()
        with patch("shutil.which", return_value=None):
            await collector.start()

        assert collector.available is False
        snapshot = await collector.get_snapshot()
        assert len(snapshot.gpus) == 0
        assert snapshot.nvidia_smi_available is False


# ---------------------------------------------------------------------------
# Ollama manager tests (Docker mocked)
# ---------------------------------------------------------------------------


class TestOllamaManager:
    """Tests for OllamaManager with mocked Docker SDK."""

    @pytest.mark.asyncio
    async def test_build_env(self):
        """Verify environment variables are correctly built from config."""
        from node_controller.models import OllamaConfig
        from node_controller.ollama_manager import OllamaManager

        config = OllamaConfig(
            num_parallel=8,
            max_loaded_models=2,
            keep_alive="10m",
            max_queue=256,
            context_length=8192,
            flash_attention=True,
            kv_cache_type="q8_0",
            env_overrides={"CUSTOM_VAR": "hello"},
        )

        env = OllamaManager._build_env(config)

        assert env["OLLAMA_NUM_PARALLEL"] == "8"
        assert env["OLLAMA_MAX_LOADED_MODELS"] == "2"
        assert env["OLLAMA_KEEP_ALIVE"] == "10m"
        assert env["OLLAMA_MAX_QUEUE"] == "256"
        assert env["OLLAMA_CONTEXT_LENGTH"] == "8192"
        assert env["OLLAMA_FLASH_ATTENTION"] == "1"
        assert env["OLLAMA_KV_CACHE_TYPE"] == "q8_0"
        assert env["CUSTOM_VAR"] == "hello"

    @pytest.mark.asyncio
    async def test_build_env_no_flash(self):
        """flash_attention=False should not set the env var."""
        from node_controller.models import OllamaConfig
        from node_controller.ollama_manager import OllamaManager

        config = OllamaConfig(flash_attention=False, kv_cache_type="f16")
        env = OllamaManager._build_env(config)
        assert "OLLAMA_FLASH_ATTENTION" not in env
        assert "OLLAMA_KV_CACHE_TYPE" not in env  # f16 is default

    @pytest.mark.asyncio
    async def test_build_device_requests_all(self):
        """gpu_devices='all' should request all GPUs."""
        from node_controller.models import OllamaConfig
        from node_controller.ollama_manager import OllamaManager

        config = OllamaConfig(gpu_devices="all")
        reqs = OllamaManager._build_device_requests(config)
        assert len(reqs) == 1
        assert reqs[0]["Count"] == -1

    @pytest.mark.asyncio
    async def test_build_device_requests_specific(self):
        """Specific GPU IDs should be passed through."""
        from node_controller.models import OllamaConfig
        from node_controller.ollama_manager import OllamaManager

        config = OllamaConfig(gpu_devices="0,1")
        reqs = OllamaManager._build_device_requests(config)
        assert len(reqs) == 1
        assert reqs[0]["DeviceIDs"] == ["0", "1"]

    @pytest.mark.asyncio
    async def test_build_device_requests_none(self):
        """gpu_devices='none' should return empty list (CPU-only mode)."""
        from node_controller.models import OllamaConfig
        from node_controller.ollama_manager import OllamaManager

        config = OllamaConfig(gpu_devices="none")
        reqs = OllamaManager._build_device_requests(config)
        assert reqs == []

        # Case-insensitive
        config2 = OllamaConfig(gpu_devices="None")
        reqs2 = OllamaManager._build_device_requests(config2)
        assert reqs2 == []

    @pytest.mark.asyncio
    async def test_status_not_found(self):
        """Status should return NOT_FOUND when container doesn't exist."""
        from node_controller.models import ContainerState
        from node_controller.ollama_manager import OllamaManager

        manager = OllamaManager(network_name="test-net", volume_name="test-vol")
        manager._client = MagicMock()
        manager._client.containers.get.side_effect = __import__(
            "docker.errors", fromlist=["NotFound"]
        ).NotFound("not found")

        result = await manager.status("non-existent")
        assert result.state == ContainerState.NOT_FOUND

    @pytest.mark.asyncio
    async def test_map_state(self):
        """Docker state strings should map to ContainerState enum."""
        from node_controller.models import ContainerState
        from node_controller.ollama_manager import OllamaManager

        assert OllamaManager._map_state("running") == ContainerState.RUNNING
        assert OllamaManager._map_state("exited") == ContainerState.STOPPED
        assert OllamaManager._map_state("restarting") == ContainerState.RESTARTING
        assert OllamaManager._map_state("created") == ContainerState.CREATING
        assert OllamaManager._map_state("unknown") == ContainerState.ERROR


# ---------------------------------------------------------------------------
# Ollama status poller tests
# ---------------------------------------------------------------------------


class TestOllamaStatusPoller:
    """Tests for status poller parsing logic."""

    def test_parse_loaded_models(self):
        """Verify /api/ps response parsing."""
        from node_controller.ollama_status import OllamaStatusPoller

        data = {
            "models": [
                {
                    "name": "llama3.2:latest",
                    "size": 5000000000,
                    "size_vram": 4500000000,
                    "digest": "abc123",
                    "expires_at": "2026-03-03T12:00:00Z",
                    "details": {"family": "llama"},
                },
            ]
        }

        models = OllamaStatusPoller._parse_loaded_models(data)
        assert len(models) == 1
        m = models[0]
        assert m.name == "llama3.2:latest"
        assert m.size == 5000000000
        assert m.size_vram == 4500000000
        assert m.digest == "abc123"
        assert m.expires_at is not None

    def test_parse_available_models(self):
        """Verify /api/tags response parsing."""
        from node_controller.ollama_status import OllamaStatusPoller

        data = {
            "models": [
                {
                    "name": "llama3.2:latest",
                    "size": 5000000000,
                    "digest": "abc123",
                    "modified_at": "2026-01-15T10:30:00Z",
                    "details": {"family": "llama"},
                },
                {
                    "name": "deepseek-r1:latest",
                    "size": 8000000000,
                    "digest": "def456",
                },
            ]
        }

        models = OllamaStatusPoller._parse_available_models(data)
        assert len(models) == 2
        assert models[0].name == "llama3.2:latest"
        assert models[1].name == "deepseek-r1:latest"
        assert models[0].modified_at is not None
        assert models[1].modified_at is None


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


class TestAuth:
    """Tests for the auth dependency."""

    @staticmethod
    def _make_test_app(tmp_path: Path, api_key: str = "test-secret-key") -> TestClient:
        """Create a test-ready app with mocked state (no lifespan/Docker)."""
        from node_controller.config import load_config

        config_file = tmp_path / "config.yml"
        config_file.write_text(
            yaml.dump({"controller": {"api_key": api_key}})
        )
        load_config(config_file)

        from node_controller.main import create_app

        app = create_app()

        # Mock app.state so route handlers don't fail on missing services
        mock_manager = MagicMock()
        mock_manager.status = AsyncMock(
            return_value=MagicMock(state=MagicMock(value="running"))
        )
        mock_gpu = MagicMock()
        mock_gpu.get_snapshot = AsyncMock(
            return_value=MagicMock(nvidia_smi_available=False)
        )
        mock_poller = MagicMock()
        mock_poller.get_status = AsyncMock()

        app.state.ollama_manager = mock_manager
        app.state.gpu_collector = mock_gpu
        app.state.status_poller = mock_poller

        return TestClient(app, raise_server_exceptions=False)

    def test_valid_token(self, tmp_path: Path):
        """Valid Bearer token should pass on /health (public)."""
        client = self._make_test_app(tmp_path)
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_missing_token(self, tmp_path: Path):
        """Missing token should return 401 on protected endpoint."""
        client = self._make_test_app(tmp_path)
        resp = client.get("/config")
        assert resp.status_code in (401, 403)

    def test_invalid_token(self, tmp_path: Path):
        """Wrong token should return 403."""
        client = self._make_test_app(tmp_path)
        resp = client.get(
            "/config",
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 403

    def test_correct_token_passes(self, tmp_path: Path):
        """Correct Bearer token should return 200 on protected endpoint."""
        client = self._make_test_app(tmp_path, api_key="my-secret")
        resp = client.get(
            "/config",
            headers={"Authorization": "Bearer my-secret"},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Models (Pydantic) tests
# ---------------------------------------------------------------------------


class TestModels:
    """Tests for Pydantic model serialization."""

    def test_ollama_config_defaults(self):
        from node_controller.models import OllamaConfig

        cfg = OllamaConfig()
        assert cfg.num_parallel == 4
        assert cfg.flash_attention is True
        assert cfg.kv_cache_type == "q8_0"
        assert cfg.preload_models == []
        assert cfg.env_overrides == {}

    def test_reconfigure_request_partial(self):
        from node_controller.models import ReconfigureRequest

        req = ReconfigureRequest(num_parallel=8)
        dumped = req.model_dump(exclude_none=True)
        assert dumped == {"num_parallel": 8}

    def test_node_status_serialization(self):
        from node_controller.models import (
            ContainerState,
            ContainerStatus,
            GpuSnapshot,
            NodeStatus,
            OllamaConfig,
            OllamaStatus,
        )

        status = NodeStatus(
            timestamp=datetime(2026, 3, 3, tzinfo=timezone.utc),
            container=ContainerStatus(
                state=ContainerState.RUNNING,
                container_name="ollama-server",
                container_id="abc123",
            ),
            ollama=OllamaStatus(reachable=True, version="0.5.0"),
            gpu=GpuSnapshot(
                timestamp=datetime(2026, 3, 3, tzinfo=timezone.utc),
                nvidia_smi_available=True,
            ),
            config=OllamaConfig(),
        )

        data = status.model_dump(mode="json")
        assert data["container"]["state"] == "running"
        assert data["ollama"]["reachable"] is True
        assert data["config"]["num_parallel"] == 4


# ---------------------------------------------------------------------------
# New feature tests
# ---------------------------------------------------------------------------


class TestNewOllamaEnvVars:
    """Tests for the new Ollama env var fields."""

    @pytest.mark.asyncio
    async def test_build_env_sched_spread(self):
        from node_controller.models import OllamaConfig
        from node_controller.ollama_manager import OllamaManager

        config = OllamaConfig(sched_spread=True)
        env = OllamaManager._build_env(config)
        assert env["OLLAMA_SCHED_SPREAD"] == "1"

    @pytest.mark.asyncio
    async def test_build_env_multiuser_cache(self):
        from node_controller.models import OllamaConfig
        from node_controller.ollama_manager import OllamaManager

        config = OllamaConfig(multiuser_cache=True)
        env = OllamaManager._build_env(config)
        assert env["OLLAMA_MULTIUSER_CACHE"] == "1"

    @pytest.mark.asyncio
    async def test_build_env_gpu_overhead(self):
        from node_controller.models import OllamaConfig
        from node_controller.ollama_manager import OllamaManager

        config = OllamaConfig(gpu_overhead_bytes=536870912)  # 512 MB
        env = OllamaManager._build_env(config)
        assert env["OLLAMA_GPU_OVERHEAD"] == "536870912"

    @pytest.mark.asyncio
    async def test_build_env_load_timeout(self):
        from node_controller.models import OllamaConfig
        from node_controller.ollama_manager import OllamaManager

        config = OllamaConfig(load_timeout="10m")
        env = OllamaManager._build_env(config)
        assert env["OLLAMA_LOAD_TIMEOUT"] == "10m"

    @pytest.mark.asyncio
    async def test_build_env_origins(self):
        from node_controller.models import OllamaConfig
        from node_controller.ollama_manager import OllamaManager

        config = OllamaConfig(origins=["http://localhost:3000", "https://app.local"])
        env = OllamaManager._build_env(config)
        assert env["OLLAMA_ORIGINS"] == "http://localhost:3000,https://app.local"

    @pytest.mark.asyncio
    async def test_build_env_noprune(self):
        from node_controller.models import OllamaConfig
        from node_controller.ollama_manager import OllamaManager

        config = OllamaConfig(noprune=True)
        env = OllamaManager._build_env(config)
        assert env["OLLAMA_NOPRUNE"] == "1"

    @pytest.mark.asyncio
    async def test_build_env_defaults_do_not_set_optional(self):
        """Default config should NOT set optional env vars."""
        from node_controller.models import OllamaConfig
        from node_controller.ollama_manager import OllamaManager

        env = OllamaManager._build_env(OllamaConfig())
        assert "OLLAMA_SCHED_SPREAD" not in env
        assert "OLLAMA_MULTIUSER_CACHE" not in env
        assert "OLLAMA_GPU_OVERHEAD" not in env
        assert "OLLAMA_LOAD_TIMEOUT" not in env
        assert "OLLAMA_ORIGINS" not in env
        assert "OLLAMA_NOPRUNE" not in env

    @pytest.mark.asyncio
    async def test_env_overrides_take_precedence(self):
        """env_overrides should override computed values."""
        from node_controller.models import OllamaConfig
        from node_controller.ollama_manager import OllamaManager

        config = OllamaConfig(
            num_parallel=4,
            env_overrides={"OLLAMA_NUM_PARALLEL": "99", "CUSTOM": "yes"},
        )
        env = OllamaManager._build_env(config)
        assert env["OLLAMA_NUM_PARALLEL"] == "99"
        assert env["CUSTOM"] == "yes"


class TestModelCreateRequest:
    """Tests for the new model create/show Pydantic models."""

    def test_model_create_request(self):
        from node_controller.models import ModelCreateRequest

        req = ModelCreateRequest(
            name="llama3.2-code:8k",
            modelfile="FROM llama3.2\nPARAMETER num_ctx 8192",
        )
        assert req.name == "llama3.2-code:8k"
        assert "num_ctx" in req.modelfile

    def test_model_info_response(self):
        from node_controller.models import ModelInfoResponse

        resp = ModelInfoResponse(
            name="llama3.2:latest",
            modelfile="FROM llama3.2",
            parameters="num_ctx 4096",
            template="{{ .System }}",
            details={"family": "llama"},
            model_info={"general.architecture": "llama"},
        )
        data = resp.model_dump()
        assert data["name"] == "llama3.2:latest"
        assert data["model_info"]["general.architecture"] == "llama"


class TestReconfigureLock:
    """Tests for the reconfigure asyncio.Lock."""

    @pytest.mark.asyncio
    async def test_reconfigure_lock_exists(self):
        """Manager should have a reconfigure lock for concurrent safety."""
        from node_controller.ollama_manager import OllamaManager

        manager = OllamaManager(network_name="test", volume_name="test")
        assert hasattr(manager, '_reconfigure_lock')
        assert isinstance(manager._reconfigure_lock, asyncio.Lock)


class TestRestartFieldsCompleteness:
    """Verify all env-var-based Ollama fields are in _RESTART_FIELDS."""

    def test_new_fields_in_restart_set(self):
        from node_controller.config import _RESTART_FIELDS

        expected_new = {
            "sched_spread", "multiuser_cache", "gpu_overhead_bytes",
            "load_timeout", "origins", "noprune",
        }
        for field in expected_new:
            assert field in _RESTART_FIELDS, f"'{field}' missing from _RESTART_FIELDS"

    def test_reconfigure_new_fields_triggers_restart(self, tmp_path: Path):
        """Changing new env-var fields should require restart."""
        from node_controller.config import apply_reconfigure, load_config

        config_file = tmp_path / "config.yml"
        config_file.write_text(yaml.dump({"ollama": {}}))
        load_config(config_file)

        _, needs_restart, changed = apply_reconfigure({"sched_spread": True})
        assert needs_restart is True
        assert "sched_spread" in changed

        _, needs_restart, changed = apply_reconfigure({"multiuser_cache": True})
        assert needs_restart is True
        assert "multiuser_cache" in changed

        _, needs_restart, changed = apply_reconfigure({"gpu_overhead_bytes": 500_000_000})
        assert needs_restart is True
        assert "gpu_overhead_bytes" in changed


class TestModelsPath:
    """Test that models_path default is consistent with volume mount."""

    def test_default_models_path(self):
        from node_controller.models import OllamaConfig

        cfg = OllamaConfig()
        # Must match the default Ollama models directory
        assert cfg.models_path == "/root/.ollama/models"

    @pytest.mark.asyncio
    async def test_models_path_in_env(self):
        """OLLAMA_MODELS env var should be set from models_path config."""
        from node_controller.models import OllamaConfig
        from node_controller.ollama_manager import OllamaManager

        config = OllamaConfig(models_path="/custom/models")
        env = OllamaManager._build_env(config)
        assert env["OLLAMA_MODELS"] == "/custom/models"


class TestPreloadTracking:
    """Tests for preload task lifecycle tracking."""

    @pytest.mark.asyncio
    async def test_preload_tasks_list_exists(self):
        from node_controller.ollama_manager import OllamaManager

        manager = OllamaManager(network_name="test", volume_name="test")
        assert isinstance(manager._preload_tasks, list)
        assert len(manager._preload_tasks) == 0
