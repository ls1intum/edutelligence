"""
Request lifecycle coverage for SDI + scheduler integration.
"""

import unittest
from unittest.mock import patch

from logos.queue import PriorityQueueManager
from logos.scheduling.simple_priority_scheduler import SimplePriorityScheduler
from logos.sdi.azure_facade import AzureSchedulingDataFacade
from logos.sdi.ollama_facade import OllamaSchedulingDataFacade

from .sdi_test_utils import create_ollama_api_response, create_task


class TestRequestLifecycleSequential(unittest.TestCase):
    """Test complete request lifecycle with sequential execution and queue progression."""

    def setUp(self):
        self.queue_mgr = PriorityQueueManager()
        self.ollama_facade = OllamaSchedulingDataFacade(self.queue_mgr)
        self.ollama_facade.register_model(1, "ollama", "https://gpu.aet.cit.tum.de/api", "llama3.3:latest", 65536, provider_id=4)

        self.scheduler = SimplePriorityScheduler(queue_manager=self.queue_mgr, sdi_facades={"ollama": self.ollama_facade})

    def test_sequential_execution_with_queue_draining(self):
        ollama_response = create_ollama_api_response({1: True})
        with patch("requests.get", return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        for i in range(5):
            task = create_task(i, model_id=1, priority=5)
            self.scheduler.enqueue(task)

        status = self.ollama_facade.get_model_status(1)
        self.assertEqual(status.queue_state.total, 5)
        self.assertEqual(status.active_requests, 0)

        work_table = {1: 1}
        for expected_remaining in [4, 3, 2, 1, 0]:
            task = self.scheduler.schedule(work_table)
            self.assertIsNotNone(task)

            self.ollama_facade.on_request_start(f"req-{task.get_id()}", model_id=1)
            self.ollama_facade.on_request_begin_processing(f"req-{task.get_id()}")

            status = self.ollama_facade.get_model_status(1)
            self.assertEqual(status.queue_state.total, expected_remaining)
            self.assertEqual(status.active_requests, 1)

            metrics = self.ollama_facade.on_request_complete(
                f"req-{task.get_id()}",
                was_cold_start=False,
                duration_ms=100,
            )
            self.assertIsNotNone(metrics)

            status = self.ollama_facade.get_model_status(1)
            self.assertEqual(status.active_requests, 0)

        self.assertTrue(self.scheduler.is_empty())
        status = self.ollama_facade.get_model_status(1)
        self.assertEqual(status.queue_state.total, 0)
        self.assertEqual(status.active_requests, 0)


class TestRequestLifecycleParallel(unittest.TestCase):
    """Test parallel execution with capacity limits and queue progression."""

    def setUp(self):
        self.queue_mgr = PriorityQueueManager()
        self.ollama_facade = OllamaSchedulingDataFacade(self.queue_mgr)
        self.ollama_facade.register_model(1, "ollama", "https://gpu.aet.cit.tum.de/api", "llama3.3:latest", 65536, provider_id=4)
        self.scheduler = SimplePriorityScheduler(queue_manager=self.queue_mgr, sdi_facades={"ollama": self.ollama_facade})

    def test_parallel_execution_with_capacity_limits(self):
        ollama_response = create_ollama_api_response({1: True})
        with patch("requests.get", return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        for i in range(10):
            task = create_task(i, model_id=1, priority=5)
            self.scheduler.enqueue(task)

        status = self.ollama_facade.get_model_status(1)
        self.assertEqual(status.queue_state.total, 10)
        self.assertEqual(status.active_requests, 0)

        work_table = {1: 3}
        active_tasks = []
        for _ in range(3):
            task = self.scheduler.schedule(work_table)
            self.assertIsNotNone(task)
            self.ollama_facade.on_request_start(f"req-{task.get_id()}", model_id=1)
            self.ollama_facade.on_request_begin_processing(f"req-{task.get_id()}")
            active_tasks.append(task)

        status = self.ollama_facade.get_model_status(1)
        self.assertEqual(status.queue_state.total, 7)
        self.assertEqual(status.active_requests, 3)

        for task in active_tasks:
            self.ollama_facade.on_request_complete(f"req-{task.get_id()}", was_cold_start=False, duration_ms=200)

        status = self.ollama_facade.get_model_status(1)
        self.assertEqual(status.active_requests, 0)


class TestRequestLifecycleMixedPriority(unittest.TestCase):
    """Test request lifecycle with mixed priorities - verify HIGH executes first."""

    def setUp(self):
        self.queue_mgr = PriorityQueueManager()
        self.ollama_facade = OllamaSchedulingDataFacade(self.queue_mgr)
        self.ollama_facade.register_model(1, "ollama", "https://gpu.aet.cit.tum.de/api", "llama3.3:latest", 65536, provider_id=4)
        self.scheduler = SimplePriorityScheduler(queue_manager=self.queue_mgr, sdi_facades={"ollama": self.ollama_facade})

    def test_lifecycle_respects_priority_ordering(self):
        ollama_response = create_ollama_api_response({1: True})
        with patch("requests.get", return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        for i, priority in enumerate([1, 1, 5, 5, 10, 10]):
            task = create_task(i, model_id=1, priority=priority)
            self.scheduler.enqueue(task)

        status = self.ollama_facade.get_model_status(1)
        self.assertEqual(status.queue_state.low, 2)
        self.assertEqual(status.queue_state.normal, 2)
        self.assertEqual(status.queue_state.high, 2)
        self.assertEqual(status.queue_state.total, 6)

        work_table = {1: 1}
        executed_ids = []
        for _ in range(6):
            task = self.scheduler.schedule(work_table)
            self.assertIsNotNone(task)
            executed_ids.append(task.get_id())
            self.ollama_facade.on_request_start(f"req-{task.get_id()}", model_id=1)
            self.ollama_facade.on_request_begin_processing(f"req-{task.get_id()}")
            self.ollama_facade.on_request_complete(f"req-{task.get_id()}", was_cold_start=False, duration_ms=100)

        self.assertEqual(executed_ids[:2], [4, 5])
        self.assertEqual(executed_ids[2:4], [2, 3])
        self.assertEqual(executed_ids[4:6], [0, 1])

        status = self.ollama_facade.get_model_status(1)
        self.assertEqual(status.queue_state.total, 0)
        self.assertEqual(status.active_requests, 0)


class TestRequestLifecycleMultiProvider(unittest.TestCase):
    """Test lifecycle with both Azure and Ollama executing concurrently."""

    def setUp(self):
        self.queue_mgr = PriorityQueueManager()
        self.ollama_facade = OllamaSchedulingDataFacade(self.queue_mgr)
        self.azure_facade = AzureSchedulingDataFacade()

        self.ollama_facade.register_model(1, "ollama", "https://gpu.aet.cit.tum.de/api", "llama3.3:latest", 65536, provider_id=4)
        self.azure_facade.register_model(
            10,
            "azure",
            "azure-gpt-4-omni",
            "https://ase-se01.openai.azure.com/openai/deployments/gpt-4o/chat/completions?api-version=2024-08-01-preview",
            provider_id=2,
        )

        self.scheduler = SimplePriorityScheduler(
            queue_manager=self.queue_mgr, sdi_facades={"ollama": self.ollama_facade, "azure": self.azure_facade}
        )

    def test_concurrent_multi_provider_execution(self):
        ollama_response = create_ollama_api_response({1: True})
        with patch("requests.get", return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        for i in range(3):
            self.scheduler.enqueue(create_task(i, model_id=1, priority=5))
            self.scheduler.enqueue(create_task(i + 10, model_id=10, priority=5))

        ollama_status = self.ollama_facade.get_model_status(1)
        self.assertEqual(ollama_status.queue_state.total, 3)
        self.assertEqual(self.queue_mgr.get_state(10).total, 3)

        work_table = {1: 1, 10: 1}
        first = self.scheduler.schedule(work_table)
        self.assertIsNotNone(first)
        if first.get_id() < 10:
            self.ollama_facade.on_request_start(f"req-{first.get_id()}", model_id=1)
            self.ollama_facade.on_request_begin_processing(f"req-{first.get_id()}")

        second = self.scheduler.schedule(work_table)
        self.assertIsNotNone(second)

        if first.get_id() < 10:
            self.ollama_facade.on_request_complete(f"req-{first.get_id()}", was_cold_start=False, duration_ms=150)
            status = self.ollama_facade.get_model_status(1)
            self.assertEqual(status.active_requests, 0)

        self.assertFalse(self.scheduler.is_empty())


class TestRequestLifecycleQueueDrainComplete(unittest.TestCase):
    """Test complete queue drain with SDI verification at each step."""

    def setUp(self):
        self.queue_mgr = PriorityQueueManager()
        self.ollama_facade = OllamaSchedulingDataFacade(self.queue_mgr)
        self.ollama_facade.register_model(1, "ollama", "https://gpu.aet.cit.tum.de/api", "llama3.3:latest", 65536, provider_id=4)
        self.scheduler = SimplePriorityScheduler(queue_manager=self.queue_mgr, sdi_facades={"ollama": self.ollama_facade})

    def test_complete_queue_drain_with_sdi_verification(self):
        ollama_response = create_ollama_api_response({1: True})
        with patch("requests.get", return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        priorities = [1, 1, 1, 5, 5, 5, 10, 10]
        for i, priority in enumerate(priorities):
            task = create_task(i, model_id=1, priority=priority)
            self.scheduler.enqueue(task)

        status = self.ollama_facade.get_model_status(1)
        self.assertEqual(status.queue_state.low, 3)
        self.assertEqual(status.queue_state.normal, 3)
        self.assertEqual(status.queue_state.high, 2)
        self.assertEqual(status.queue_state.total, 8)
        self.assertEqual(status.active_requests, 0)
        self.assertTrue(status.is_loaded)

        work_table = {1: 1}
        expected_queue_depths = [7, 6, 5, 4, 3, 2, 1, 0]
        for i, expected_depth in enumerate(expected_queue_depths):
            task = self.scheduler.schedule(work_table)
            self.assertIsNotNone(task, f"Task {i} should be schedulable")

            status = self.ollama_facade.get_model_status(1)
            self.assertEqual(status.queue_state.total, expected_depth)

            self.ollama_facade.on_request_start(f"req-{task.get_id()}", model_id=1, priority="normal")
            self.ollama_facade.on_request_begin_processing(f"req-{task.get_id()}")

            status = self.ollama_facade.get_model_status(1)
            self.assertEqual(status.active_requests, 1)

            metrics = self.ollama_facade.on_request_complete(
                f"req-{task.get_id()}",
                was_cold_start=(i == 0),
                duration_ms=100 + (i * 10),
            )
            self.assertIsNotNone(metrics)
            self.assertEqual(metrics.duration_ms, 100 + (i * 10))

            status = self.ollama_facade.get_model_status(1)
            self.assertEqual(status.active_requests, 0)

        self.assertTrue(self.scheduler.is_empty())
        status = self.ollama_facade.get_model_status(1)
        self.assertEqual(status.queue_state.total, 0)
        self.assertEqual(status.active_requests, 0)
        self.assertTrue(status.is_loaded)

        task = self.scheduler.schedule(work_table)
        self.assertIsNone(task)
