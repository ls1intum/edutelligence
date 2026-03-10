"""
Unit tests for the Node Controller.

Tests cover: config loading/saving, GPU parsing, Ollama manager (process-based),
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
            import os

            old = os.getcwd()
            try:
                os.chdir(d)
                cfg = load_config()
                assert isinstance(cfg, AppConfig)
                assert cfg.ollama.num_parallel == 4
                assert cfg.controller.port == 8444
            finally:
                os.chdir(old)

    def test_load_from_file(self, tmp_path: Path):
        """Loading from a valid YAML file should parse correctly."""
        from node_controller.config import load_config

        config_data = {
            "controller": {"port": 9999, "api_key": "test-key"},
            "ollama": {
                "num_parallel": 8,
                "port": 11435,
                "ollama_binary": "/usr/bin/ollama",
            },
        }
        config_file = tmp_path / "config.yml"
        config_file.write_text(yaml.dump(config_data))

        cfg = load_config(config_file)
        assert cfg.controller.port == 9999
        assert cfg.controller.api_key == "test-key"
        assert cfg.ollama.num_parallel == 8
        assert cfg.ollama.port == 11435
        assert cfg.ollama.ollama_binary == "/usr/bin/ollama"
        # Defaults preserved for unspecified fields
        assert cfg.ollama.max_loaded_models == 3
        assert cfg.ollama.flash_attention is True

    def test_save_config(self, tmp_path: Path):
        """Saving should write a valid YAML file."""
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
# Ollama manager tests (process-based)
# ---------------------------------------------------------------------------


class TestOllamaManager:
    """Tests for OllamaManager process management."""

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
        assert env["OLLAMA_HOST"] == "0.0.0.0:11435"

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
    async def test_build_env_gpu_devices_specific(self):
        """Specific GPU IDs should set CUDA_VISIBLE_DEVICES."""
        from node_controller.models import OllamaConfig
        from node_controller.ollama_manager import OllamaManager

        config = OllamaConfig(gpu_devices="0,1")
        env = OllamaManager._build_env(config)
        assert env["CUDA_VISIBLE_DEVICES"] == "0,1"

    @pytest.mark.asyncio
    async def test_build_env_gpu_devices_all(self):
        """gpu_devices='all' should not set CUDA_VISIBLE_DEVICES."""
        from node_controller.models import OllamaConfig
        from node_controller.ollama_manager import OllamaManager

        config = OllamaConfig(gpu_devices="all")
        env = OllamaManager._build_env(config)
        assert "CUDA_VISIBLE_DEVICES" not in env

    @pytest.mark.asyncio
    async def test_build_env_gpu_devices_none(self):
        """gpu_devices='none' should set CUDA_VISIBLE_DEVICES to empty string."""
        from node_controller.models import OllamaConfig
        from node_controller.ollama_manager import OllamaManager

        config = OllamaConfig(gpu_devices="none")
        env = OllamaManager._build_env(config)
        assert env["CUDA_VISIBLE_DEVICES"] == ""

        # Case-insensitive
        config2 = OllamaConfig(gpu_devices="None")
        env2 = OllamaManager._build_env(config2)
        assert env2["CUDA_VISIBLE_DEVICES"] == ""

    @pytest.mark.asyncio
    async def test_build_env_llm_library(self):
        """llm_library should set OLLAMA_LLM_LIBRARY."""
        from node_controller.models import OllamaConfig
        from node_controller.ollama_manager import OllamaManager

        config = OllamaConfig(llm_library="cuda_v12")
        env = OllamaManager._build_env(config)
        assert env["OLLAMA_LLM_LIBRARY"] == "cuda_v12"

    @pytest.mark.asyncio
    async def test_build_env_llm_library_empty(self):
        """Empty llm_library should not set OLLAMA_LLM_LIBRARY."""
        from node_controller.models import OllamaConfig
        from node_controller.ollama_manager import OllamaManager

        config = OllamaConfig(llm_library="")
        env = OllamaManager._build_env(config)
        assert "OLLAMA_LLM_LIBRARY" not in env

    @pytest.mark.asyncio
    async def test_status_not_started(self):
        """Status should return NOT_STARTED when never spawned."""
        from node_controller.models import ProcessState
        from node_controller.ollama_manager import OllamaManager

        manager = OllamaManager()
        result = manager.status()
        assert result.state == ProcessState.NOT_STARTED
        assert result.pid is None

    @pytest.mark.asyncio
    async def test_status_running(self):
        """Status should return RUNNING when process is alive."""
        from node_controller.models import ProcessState
        from node_controller.ollama_manager import OllamaManager

        manager = OllamaManager()
        manager._process = MagicMock()
        manager._process.returncode = None
        manager._process.pid = 12345

        result = manager.status()
        assert result.state == ProcessState.RUNNING
        assert result.pid == 12345

    @pytest.mark.asyncio
    async def test_status_stopped(self):
        """Status should return STOPPED when process has exited."""
        from node_controller.models import ProcessState
        from node_controller.ollama_manager import OllamaManager

        manager = OllamaManager()
        manager._process = MagicMock()
        manager._process.returncode = 0
        manager._process.pid = 12345

        result = manager.status()
        assert result.state == ProcessState.STOPPED
        assert result.pid == 12345
        assert result.return_code == 0


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
        """Create a test-ready app with mocked state (no lifespan/process)."""
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
        mock_manager.status = MagicMock(
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
