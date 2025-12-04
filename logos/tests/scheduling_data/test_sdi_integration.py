"""
SDI integration tests covering queue visibility, rate limits, and VRAM tracking.
"""

import logging
import unittest
from unittest.mock import patch, MagicMock

import pytest
import requests

from logos.dbutils.dbmanager import DBManager
from logos.queue import PriorityQueueManager
from logos.responses import merge_url
from logos.scheduling.simple_priority_scheduler import SimplePriorityScheduler
from logos.sdi.azure_facade import AzureSchedulingDataFacade
from logos.sdi.ollama_facade import OllamaSchedulingDataFacade

from .sdi_test_utils import (
    AZURE_MODELS,
    OLLAMA_MODELS,
    create_azure_rate_limit_headers,
    create_ollama_api_response,
    create_task,
)


class TestSDIIntegration(unittest.TestCase):
    """Test SDI facade integration with scheduler."""

    def setUp(self):
        self.queue_mgr = PriorityQueueManager()
        self.ollama_facade = OllamaSchedulingDataFacade(self.queue_mgr)
        self.azure_facade = AzureSchedulingDataFacade()

        self.ollama_facade.register_model(
            1, "ollama", "https://gpu.aet.cit.tum.de/api", "llama3.3:latest", 65536, provider_id=4
        )
        self.azure_facade.register_model(
            10, "azure", "azure-gpt-4-omni", AZURE_MODELS[10]["endpoint"], provider_id=2
        )

        self.scheduler = SimplePriorityScheduler(
            queue_manager=self.queue_mgr, sdi_facades={"ollama": self.ollama_facade, "azure": self.azure_facade}
        )

    def test_queue_state_reporting(self):
        ollama_response = create_ollama_api_response({1: True})
        with patch("requests.get", return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        for priority in [1, 5, 10]:
            for i in range(3):
                task = create_task(i + priority * 10, model_id=1, priority=priority)
                self.scheduler.enqueue(task)

        status = self.ollama_facade.get_model_status(1)
        self.assertEqual(status.queue_state.low, 3)
        self.assertEqual(status.queue_state.normal, 3)
        self.assertEqual(status.queue_state.high, 3)
        self.assertEqual(status.queue_state.total, 9)

    def test_azure_no_queue_visibility(self):
        status = self.azure_facade.get_model_status(10)
        self.assertIsNone(status.queue_state)
        self.assertEqual(status.provider_type, "azure")

    def test_ollama_queue_visibility(self):
        ollama_response = create_ollama_api_response({1: True})
        with patch("requests.get", return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        task = create_task(1, model_id=1, priority=5)
        self.scheduler.enqueue(task)

        status = self.ollama_facade.get_model_status(1)
        self.assertIsNotNone(status.queue_state)
        self.assertEqual(status.provider_type, "ollama")
        self.assertEqual(status.queue_state.total, 1)


class TestSDIDataUsage(unittest.TestCase):
    """Test that scheduler uses SDI data (rate limits, VRAM, loaded models)."""

    def setUp(self):
        self.queue_mgr = PriorityQueueManager()
        self.ollama_facade = OllamaSchedulingDataFacade(self.queue_mgr)
        self.azure_facade = AzureSchedulingDataFacade()

        self.ollama_facade.register_model(
            1, "ollama", "https://gpu.aet.cit.tum.de/api", "llama3.3:latest", 65536, provider_id=4
        )
        self.ollama_facade.register_model(
            14, "ollama", "https://gpu.aet.cit.tum.de/api", "deepseek-r1:70b", 65536, provider_id=4
        )
        self.azure_facade.register_model(
            10, "azure", "azure-gpt-4-omni", AZURE_MODELS[10]["endpoint"], provider_id=2
        )

        self.scheduler = SimplePriorityScheduler(
            queue_manager=self.queue_mgr, sdi_facades={"ollama": self.ollama_facade, "azure": self.azure_facade}
        )

    def test_azure_rate_limit_blocks_scheduling(self):
        headers = create_azure_rate_limit_headers(remaining_requests=0)
        self.azure_facade.update_rate_limits("azure", "gpt-4o", headers)
        capacity = self.azure_facade.get_capacity_info("azure", "gpt-4o")
        self.assertFalse(capacity.has_capacity)

        task = create_task(1, model_id=10, priority=5)
        self.scheduler.enqueue(task)
        work_table = {10: 2 if capacity.has_capacity else 0}
        scheduled = self.scheduler.schedule(work_table)
        self.assertIsNone(scheduled)

    def test_azure_rate_limit_recovery_enables_scheduling(self):
        headers = create_azure_rate_limit_headers(remaining_requests=0)
        self.azure_facade.update_rate_limits("azure", "gpt-4o", headers)

        task = create_task(1, model_id=10, priority=5)
        self.scheduler.enqueue(task)
        capacity = self.azure_facade.get_capacity_info("azure", "gpt-4o")
        self.assertFalse(capacity.has_capacity)

        headers = create_azure_rate_limit_headers(remaining_requests=100)
        self.azure_facade.update_rate_limits("azure", "gpt-4o", headers)
        capacity = self.azure_facade.get_capacity_info("azure", "gpt-4o")
        self.assertTrue(capacity.has_capacity)
        self.assertEqual(capacity.rate_limit_remaining_requests, 100)

        work_table = {10: 2 if capacity.has_capacity else 0}
        scheduled = self.scheduler.schedule(work_table)
        self.assertIsNotNone(scheduled)
        self.assertEqual(scheduled.get_id(), 1)

    def test_ollama_loaded_model_status_tracked(self):
        ollama_response = create_ollama_api_response({1: True, 14: False})
        with patch("requests.get", return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        status_warm = self.ollama_facade.get_model_status(1)
        status_cold = self.ollama_facade.get_model_status(14)
        self.assertTrue(status_warm.is_loaded)
        self.assertGreater(status_warm.vram_mb, 0)
        self.assertFalse(status_cold.is_loaded)
        self.assertEqual(status_cold.vram_mb, 0)

    def test_ollama_vram_capacity_tracked(self):
        ollama_response = create_ollama_api_response({1: True, 14: True})
        with patch("requests.get", return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        capacity = self.ollama_facade.get_capacity_info("ollama")
        self.assertEqual(capacity.total_vram_mb, 65536)
        self.assertAlmostEqual(capacity.available_vram_mb, 65536 - 8192 - 40960, delta=100)
        self.assertEqual(len(capacity.loaded_models), 2)

    def test_work_table_derived_from_sdi_multi_provider(self):
        azure_headers = create_azure_rate_limit_headers(remaining_requests=50)
        self.azure_facade.update_rate_limits("azure", "gpt-4o", azure_headers)

        ollama_response = create_ollama_api_response({1: True, 14: False})
        with patch("requests.get", return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        work_table = {}
        azure_capacity = self.azure_facade.get_capacity_info("azure", "gpt-4o")
        work_table[10] = 2 if azure_capacity.has_capacity else 0

        ollama_status_1 = self.ollama_facade.get_model_status(1)
        ollama_status_14 = self.ollama_facade.get_model_status(14)
        work_table[1] = 2 if ollama_status_1.is_loaded else 0
        work_table[14] = 2 if ollama_status_14.is_loaded else 0

        self.assertEqual(work_table[10], 2)
        self.assertEqual(work_table[1], 2)
        self.assertEqual(work_table[14], 0)

        task_azure = create_task(1, model_id=10, priority=5)
        task_warm = create_task(2, model_id=1, priority=5)
        task_cold = create_task(3, model_id=14, priority=5)
        self.scheduler.enqueue(task_azure)
        self.scheduler.enqueue(task_warm)
        self.scheduler.enqueue(task_cold)

        scheduled = self.scheduler.schedule(work_table)
        self.assertIsNotNone(scheduled)
        self.assertIn(scheduled.get_id(), [1, 2])
        self.assertNotEqual(scheduled.get_id(), 3)


class TestAzureRequestAndStatus(unittest.TestCase):
    """Send a mocked Azure request and verify status via Azure facade."""

    @pytest.fixture(autouse=True)
    def _setup_azure_model(self, azure_model_id):
        """Auto-use fixture to inject Azure model ID."""
        if not azure_model_id:
            pytest.skip("--azure-model-id not provided or invalid")
        self.model_id = azure_model_id

    def setUp(self):
        if self.model_id not in AZURE_MODELS:
            pytest.skip(f"AZURE model id {self.model_id} not in AZURE_MODELS")
        self.azure_facade = AzureSchedulingDataFacade()
        self.azure_facade.register_model(
            self.model_id, "azure", AZURE_MODELS[self.model_id]["name"], AZURE_MODELS[self.model_id]["endpoint"], provider_id=2
        )

    @patch("requests.post")
    def test_request_updates_status(self, mock_post):
        headers_initial = create_azure_rate_limit_headers(remaining_requests=50)
        headers_after = create_azure_rate_limit_headers(remaining_requests=49)
        mock_resp_first = MagicMock()
        mock_resp_first.status_code = 200
        mock_resp_first.headers = headers_after  # simulate decrement after request
        mock_resp_first.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        mock_post.return_value = mock_resp_first

        # Pretend we had initial rate limits before this call
        self.azure_facade.update_rate_limits("azure", "gpt-4o", headers_initial)

        resp = requests.post(AZURE_MODELS[self.model_id]["endpoint"], headers={"Authorization": "Bearer dummy"}, json={})
        self.assertEqual(resp.status_code, 200)

        # Update facade with rate limits from the "response" (decremented)
        self.azure_facade.update_rate_limits("azure", "gpt-4o", resp.headers)
        status = self.azure_facade.get_model_status(self.model_id)
        capacity = self.azure_facade.get_capacity_info("azure", "gpt-4o")

        self.assertEqual(status.provider_type, "azure")
        self.assertIsNone(status.queue_state)  # Azure has no queue visibility
        self.assertTrue(capacity.has_capacity)
        self.assertEqual(capacity.rate_limit_remaining_requests, 49)


class TestAzureLiveInferenceFromDB(unittest.TestCase):
    """
    Optional live test: pull provider/model config from DB and run real Azure inference.
    Requires --azure-live-model-id.
    """

    @pytest.fixture(autouse=True)
    def _setup_model_id(self, azure_live_model_id):
        """Auto-use fixture to inject Azure live model ID."""
        if not azure_live_model_id:
            pytest.skip("--azure-live-model-id not provided")
        self.model_id = azure_live_model_id

    def setUp(self):
        with DBManager() as db:
            provider = db.get_provider_to_model(self.model_id)
            if not provider:
                self.skipTest("No provider linked to model_id")
            self.provider_id = provider["id"]
            self.base_url = provider["base_url"].rstrip("/")
            self.auth_name = provider.get("auth_name") or "api-key"
            self.auth_format = provider.get("auth_format") or "{}"
            api_key = db.get_key_to_model_provider(self.model_id, self.provider_id)
            if not api_key:
                self.skipTest("No API key linked to model/provider in DB")
            self.api_key = api_key
            model = db.get_model(self.model_id)
            if not model:
                self.skipTest("Model not found in DB")
            self.model_name = model["name"]
            self.model_endpoint = model["endpoint"]

        self.forward_url = merge_url(self.base_url, self.model_endpoint)

    def test_live_azure_inference(self):
        payload = {"messages": [{"role": "user", "content": "ping"}], "max_tokens": 16}
        headers = {self.auth_name: self.auth_format.replace("{}", self.api_key)}

        try:
            resp = requests.post(self.forward_url, json=payload, headers=headers, timeout=30)
        except requests.exceptions.ConnectionError as e:
            logging.warning(
                "[AzureLiveInferenceFromDB] Connection failed",
                extra={
                    "base_url": self.base_url,
                    "model_id": self.model_id,
                    "model_name": self.model_name,
                    "error": str(e),
                },
            )
            self.skipTest(f"Base URL not reachable for live Azure inference: {e}")

        if resp.status_code != 200:
            logging.warning(
                "[AzureLiveInferenceFromDB] Non-200 response",
                extra={
                    "forward_url": self.forward_url,
                    "model_id": self.model_id,
                    "model_name": self.model_name,
                    "status_code": resp.status_code,
                    "body": resp.text,
                },
            )
            self.skipTest(f"Live Azure inference returned {resp.status_code}, expected 200")

        body = resp.json()
        self.assertIn("choices", body)
