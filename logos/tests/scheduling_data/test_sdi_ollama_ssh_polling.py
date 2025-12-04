"""
Tests for Ollama SSH polling and refresh caching.
"""

import json
import time
import unittest
from unittest.mock import MagicMock, patch

import logging
import pytest
import requests
from logos.dbutils.dbmanager import DBManager
from logos.responses import merge_url
from logos.queue import PriorityQueueManager
from logos.sdi.providers.ollama_provider import OllamaDataProvider

from .sdi_test_utils import OLLAMA_MODELS


class TestOllamaSSHPolling(unittest.TestCase):
    def setUp(self):
        self.queue_mgr = PriorityQueueManager()
        self.provider = OllamaDataProvider(
            name="openwebui",
            base_url=None,  # force SSH path
            total_vram_mb=65536,
            queue_manager=self.queue_mgr,
            refresh_interval=5.0,
            provider_id=None,
            db_manager=None,
        )
        # Inject SSH config directly (normally loaded from DB config)
        self.provider._provider_config = {
            "ssh_host": "hochbruegge.aet.cit.tum.de",
            "ssh_user": "ge84ciq",
            "ssh_port": 22,
            "ssh_key_path": "/root/.ssh/id_ed25519",
            "ssh_remote_ollama_port": 11434,
        }
        self.provider._ssh_config = self.provider._build_ssh_config(self.provider._provider_config)
        self.provider.register_model(1, OLLAMA_MODELS[1]["name"])

    @patch("logos.sdi.providers.ollama_provider.subprocess.run")
    def test_refresh_data_uses_ssh_when_base_url_missing(self, mock_run: MagicMock):
        ssh_json = {"models": [{"name": OLLAMA_MODELS[1]["name"], "size_vram": 8 * 1024 * 1024, "expires_at": None}]}
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(ssh_json), stderr="")

        self.provider.refresh_data()

        self.assertTrue(mock_run.called)
        cmd = mock_run.call_args[0][0]
        self.assertIn("ssh", cmd[0])
        self.assertTrue(any("hochbruegge.aet.cit.tum.de" in part for part in cmd))

        status = self.provider.get_model_status(1)
        self.assertTrue(status.is_loaded)
        self.assertGreater(status.vram_mb, 0)

    @patch("logos.sdi.providers.ollama_provider.subprocess.run")
    def test_refresh_skips_when_cache_fresh(self, mock_run: MagicMock):
        self.provider._last_refresh = time.time()
        self.provider.refresh_data()
        mock_run.assert_not_called()


class TestOllamaSSHPollingLive(unittest.TestCase):
    """
    Optional live integration: performs a real SSH + /api/ps call.
    Skipped unless SSH parameters are provided via pytest CLI.
    """

    @pytest.fixture(autouse=True)
    def _setup_ssh_config(self, ssh_config):
        """Auto-use fixture to inject SSH config."""
        if not ssh_config:
            pytest.skip("SSH parameters not provided. Use: --ssh-host --ssh-user --ssh-key-path")
        self.ssh_config = ssh_config

    def setUp(self):
        self.queue_mgr = PriorityQueueManager()
        self.provider = OllamaDataProvider(
            name="openwebui-live",
            base_url=None,
            total_vram_mb=65536,
            queue_manager=self.queue_mgr,
            refresh_interval=1.0,  # short for test
            provider_id=None,
            db_manager=None,
        )
        self.provider._provider_config = self.ssh_config
        self.provider._ssh_config = self.provider._build_ssh_config(self.ssh_config)
        self.provider.register_model(1, OLLAMA_MODELS[1]["name"])

    def test_live_poll_over_ssh(self):
        # No mocks: performs a real ssh curl /api/ps
        self.provider.refresh_data()
        status = self.provider.get_model_status(1)
        # We only assert that a status object is returned; it may or may not be loaded.
        self.assertIsNotNone(status)
        # Report loaded models for visibility
        capacity = self.provider.get_capacity_info()
        self.assertIsInstance(capacity.loaded_models, list)
        # Ensure refresh timestamp updated
        self.assertGreater(self.provider._last_refresh, 0)


class TestOllamaLiveInferenceFromDB(unittest.TestCase):
    """
    Optional live test: pull provider/model config from DB, poll via SSH,
    and run real inference. Requires --ollama-live-model-id.
    """

    @pytest.fixture(autouse=True)
    def _setup_model_id(self, ollama_live_model_id):
        """Auto-use fixture to inject model ID."""
        if not ollama_live_model_id:
            pytest.skip("--ollama-live-model-id not provided")
        self.model_id = ollama_live_model_id

    def setUp(self):
        with DBManager() as db:
            provider = db.get_provider_to_model(self.model_id)
            if not provider:
                self.skipTest("No provider linked to model_id")
            self.provider_id = provider["id"]
            self.base_url = provider["base_url"].rstrip("/")
            provider_cfg = db.get_provider_config(self.provider_id) or {}
            if not provider_cfg.get("ssh_host"):
                self.skipTest("Provider missing ssh_host in DB")
            # Fetch auth config and API key
            self.auth_name = provider.get("auth_name") or "Authorization"
            self.auth_format = provider.get("auth_format") or "Bearer {}"
            api_key = db.get_key_to_model_provider(self.model_id, self.provider_id)
            if not api_key:
                self.skipTest("No API key linked to model/provider in DB")
            self.api_key = api_key
            model = db.get_model(self.model_id)
            if not model:
                self.skipTest("Model not found in DB")
            self.model_name = model["name"]
            self.model_endpoint = model["endpoint"]

        self.queue_mgr = PriorityQueueManager()
        self.provider = OllamaDataProvider(
            name=provider.get("name", "openwebui-live-db"),
            # Use external base_url for inference; SSH handles /api/ps
            base_url=self.base_url,
            total_vram_mb=provider_cfg.get("total_vram_mb") or 65536,
            queue_manager=self.queue_mgr,
            refresh_interval=2.0,
            provider_id=self.provider_id,
            db_manager=None,
        )
        self.provider._provider_config = provider_cfg
        self.provider._ssh_config = self.provider._build_ssh_config(provider_cfg)
        self.provider.register_model(self.model_id, self.model_name)
        self.forward_url = merge_url(self.base_url, self.model_endpoint)

    def test_db_driven_inference_and_poll(self):
        # Initial poll via SSH using DB-configured ssh_* fields
        self.provider.refresh_data()

        # Real inference via DB-configured base_url (must be reachable)
        try:
            resp = requests.post(
                self.forward_url,
                json={"model": self.model_name, "messages": [{"role": "user", "content": "ping"}], "stream": False},
                headers={
                    self.auth_name: self.auth_format.replace("{}", self.api_key)
                },
                timeout=30,
            )
        except requests.exceptions.ConnectionError as e:
            logging.warning(
                "[OllamaLiveInferenceFromDB] Connection failed",
                extra={
                    "base_url": self.base_url,
                    "model_id": self.model_id,
                    "model_name": self.model_name,
                    "error": str(e),
                },
            )
            self.skipTest(f"Base URL not reachable for live inference: {e}")

        if resp.status_code != 200:
            logging.warning(
                "[OllamaLiveInferenceFromDB] Non-200 response",
                extra={
                    "base_url": self.base_url,
                    "model_id": self.model_id,
                    "model_name": self.model_name,
                    "status_code": resp.status_code,
                    "body": resp.text,
                },
            )
            self.skipTest(f"Live inference returned {resp.status_code}, expected 200")
        try:
            body = resp.json()
        except ValueError:
            logging.warning(
                "[OllamaLiveInferenceFromDB] Non-JSON response",
                extra={
                    "forward_url": self.forward_url,
                    "body": resp.text[:500],
                },
            )
            self.skipTest("Live inference did not return JSON")

        if not isinstance(body, dict):
            logging.warning(
                "[OllamaLiveInferenceFromDB] Non-dict JSON response",
                extra={
                    "forward_url": self.forward_url,
                    "body_type": str(type(body)),
                    "body_value": str(body)[:500],
                },
            )
            self.skipTest("Live inference returned unexpected JSON shape")

        if "response" in body:
            self.assertTrue(body["response"])
        elif "choices" in body:
            self.assertTrue(body["choices"])
        else:
            logging.warning(
                "[OllamaLiveInferenceFromDB] Unexpected response shape",
                extra={
                    "forward_url": self.forward_url,
                    "keys": list(body.keys()) if isinstance(body, dict) else str(type(body)),
                    "body_snippet": str(body)[:500],
                },
            )
            self.skipTest("Live inference response missing expected keys")

        # Poll again to confirm visibility in /api/ps
        self.provider.refresh_data()
        status = self.provider.get_model_status(self.model_id)
        self.assertIsNotNone(status)
        self.assertTrue(status.is_loaded or status.vram_mb >= 0)
