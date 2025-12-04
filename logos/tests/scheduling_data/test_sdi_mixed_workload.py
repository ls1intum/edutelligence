"""
Mixed workload and capacity distribution tests for SDI facades.
"""

import unittest
from unittest.mock import patch

from logos.queue import PriorityQueueManager
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


class TestMixedWorkload(unittest.TestCase):
    """Scenario 1: Mixed Azure + Ollama workload distribution."""

    def setUp(self):
        self.queue_mgr = PriorityQueueManager()
        self.ollama_facade = OllamaSchedulingDataFacade(queue_manager=self.queue_mgr, db_manager=None)
        self.azure_facade = AzureSchedulingDataFacade(db_manager=None)

        for model_id in [1, 14, 15]:
            self.ollama_facade.register_model(
                model_id=model_id,
                provider_name="ollama",
                ollama_admin_url="https://gpu.aet.cit.tum.de/api",
                model_name=OLLAMA_MODELS[model_id]["name"],
                total_vram_mb=65536,
                provider_id=4,
            )

        for model_id in [10, 12, 21]:
            self.azure_facade.register_model(
                model_id=model_id,
                provider_name="azure",
                model_name=AZURE_MODELS[model_id]["name"],
                model_endpoint=AZURE_MODELS[model_id]["endpoint"],
                provider_id=2,
            )

        self.scheduler = SimplePriorityScheduler(
            queue_manager=self.queue_mgr,
            sdi_facades={"ollama": self.ollama_facade, "azure": self.azure_facade},
        )

    def test_low_priority_distribution(self):
        ollama_response = create_ollama_api_response({1: True, 15: True})
        with patch("requests.get", return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()
            headers = create_azure_rate_limit_headers(remaining_requests=100)
            self.azure_facade.update_rate_limits("azure", "gpt-4o", headers)

        tasks = [
            create_task(1, model_id=10, priority=1),
            create_task(2, model_id=1, priority=1),
            create_task(3, model_id=15, priority=1),
        ]
        for task in tasks:
            self.scheduler.enqueue(task)

        work_table = {10: 2, 1: 2, 15: 2}
        self.assertEqual(self.queue_mgr.get_state(10).low, 1)
        self.assertEqual(self.queue_mgr.get_state(1).low, 1)
        self.assertEqual(self.queue_mgr.get_state(15).low, 1)

        for _ in range(3):
            scheduled = self.scheduler.schedule(work_table)
            self.assertIsNotNone(scheduled)

        self.assertTrue(self.scheduler.is_empty())


class TestRateLimitHandling(unittest.TestCase):
    """Scenario 2: Azure rate limit exhaustion and failover."""

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

    def test_failover_to_ollama(self):
        headers = create_azure_rate_limit_headers(remaining_requests=0)
        self.azure_facade.update_rate_limits("azure", "gpt-4o", headers)

        ollama_response = create_ollama_api_response({1: True})
        with patch("requests.get", return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        azure_capacity = self.azure_facade.get_capacity_info("azure", "gpt-4o")
        ollama_status = self.ollama_facade.get_model_status(1)

        self.assertFalse(azure_capacity.has_capacity)
        self.assertTrue(ollama_status.is_loaded)

        task_azure = create_task(1, model_id=10, priority=5)
        task_ollama = create_task(2, model_id=1, priority=5)
        self.scheduler.enqueue(task_azure)
        self.scheduler.enqueue(task_ollama)

        work_table = {10: 2 if azure_capacity.has_capacity else 0, 1: 2 if ollama_status.is_loaded else 0}
        scheduled = self.scheduler.schedule(work_table)
        self.assertIsNotNone(scheduled)
        self.assertEqual(scheduled.get_id(), 2)

        state = self.queue_mgr.get_state(10)
        self.assertEqual(state.normal, 1)


class TestColdStartScenarios(unittest.TestCase):
    """Scenario 3: Ollama cold start handling."""

    def setUp(self):
        self.queue_mgr = PriorityQueueManager()
        self.ollama_facade = OllamaSchedulingDataFacade(self.queue_mgr)

        for model_id in [1, 14, 17, 18]:
            self.ollama_facade.register_model(
                model_id,
                "ollama",
                "https://gpu.aet.cit.tum.de/api",
                OLLAMA_MODELS[model_id]["name"],
                65536,
                provider_id=4,
            )

        self.scheduler = SimplePriorityScheduler(queue_manager=self.queue_mgr, sdi_facades={"ollama": self.ollama_facade})

    def test_warm_model_preferred(self):
        ollama_response = create_ollama_api_response({1: True, 14: False})
        with patch("requests.get", return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        status_warm = self.ollama_facade.get_model_status(1)
        status_cold = self.ollama_facade.get_model_status(14)

        self.assertTrue(status_warm.is_loaded)
        self.assertFalse(status_cold.is_loaded)

        task_warm = create_task(1, model_id=1, priority=5)
        task_cold = create_task(2, model_id=14, priority=5)
        self.scheduler.enqueue(task_warm)
        self.scheduler.enqueue(task_cold)

        work_table = {1: 2, 14: 2}
        scheduled = self.scheduler.schedule(work_table)
        self.assertIsNotNone(scheduled)

    def test_vram_constraints(self):
        ollama_response = create_ollama_api_response({14: True})
        with patch("requests.get", return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        capacity = self.ollama_facade.get_capacity_info("ollama")
        self.assertEqual(capacity.total_vram_mb, 65536)
        self.assertEqual(capacity.available_vram_mb, 65536 - 40960)
        self.assertIn("deepseek-r1:70b", capacity.loaded_models)

    def test_multiple_models_loaded(self):
        ollama_response = create_ollama_api_response({17: True, 18: True})
        with patch("requests.get", return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        capacity = self.ollama_facade.get_capacity_info("ollama")
        self.assertEqual(capacity.available_vram_mb, 65536 - 1024 - 2048)
        self.assertEqual(len(capacity.loaded_models), 2)


class TestHighTrafficBurst(unittest.TestCase):
    """Scenario 4: High traffic with queue buildup."""

    def setUp(self):
        self.queue_mgr = PriorityQueueManager()
        self.ollama_facade = OllamaSchedulingDataFacade(self.queue_mgr)

        for model_id in [1, 15, 17]:
            self.ollama_facade.register_model(
                model_id,
                "ollama",
                "https://gpu.aet.cit.tum.de/api",
                OLLAMA_MODELS[model_id]["name"],
                65536,
                provider_id=4,
            )

        self.scheduler = SimplePriorityScheduler(queue_manager=self.queue_mgr, sdi_facades={"ollama": self.ollama_facade})

    def test_queue_buildup(self):
        ollama_response = create_ollama_api_response({1: True})
        with patch("requests.get", return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        for i in range(20):
            priority = [1, 5, 10][i % 3]
            task = create_task(i, model_id=1, priority=priority)
            self.scheduler.enqueue(task)

        state = self.queue_mgr.get_state(1)
        self.assertEqual(state.total, 20)
        self.assertGreater(state.low, 0)
        self.assertGreater(state.normal, 0)
        self.assertGreater(state.high, 0)

    def test_limited_capacity_scheduling(self):
        ollama_response = create_ollama_api_response({1: True})
        with patch("requests.get", return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        for i in range(10):
            task = create_task(i, model_id=1, priority=5)
            self.scheduler.enqueue(task)

        work_table = {1: 3}
        scheduled_count = 0
        for _ in range(3):
            scheduled = self.scheduler.schedule(work_table)
            if scheduled:
                scheduled_count += 1

        self.assertEqual(scheduled_count, 3)
        state = self.queue_mgr.get_state(1)
        self.assertEqual(state.total, 7)

    def test_load_balancing_across_models(self):
        ollama_response = create_ollama_api_response({1: True, 15: True, 17: True})
        with patch("requests.get", return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        for model_id in [1, 15, 17]:
            for i in range(5):
                task = create_task(model_id * 100 + i, model_id=model_id, priority=5)
                self.scheduler.enqueue(task)

        work_table = {1: 2, 15: 2, 17: 2}

        self.assertEqual(self.queue_mgr.get_state(1).total, 5)
        self.assertEqual(self.queue_mgr.get_state(15).total, 5)
        self.assertEqual(self.queue_mgr.get_state(17).total, 5)

        for _ in range(6):
            scheduled = self.scheduler.schedule(work_table)
            self.assertIsNotNone(scheduled)
