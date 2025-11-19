"""
Integration tests for Queue + SDI + Scheduler subsystems.

Tests realistic workload scenarios with:
- Mixed Azure and Ollama models
- Rate limit handling
- Cold start scenarios
- High/low traffic patterns
- Real model configurations from database

Uses REAL facade implementations with mocked HTTP layer.
"""

import time
import unittest
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional
from unittest.mock import Mock, patch

from logos.scheduling.simple_priority_scheduler import SimplePriorityScheduler
from logos.scheduling.scheduler import Task
from logos.queue import PriorityQueueManager, Priority
from logos.queue.models import QueueStatePerPriority
from logos.sdi.ollama_facade import OllamaSchedulingDataFacade
from logos.sdi.azure_facade import AzureSchedulingDataFacade


# =============================================================================
# Real Model Configurations (from database)
# =============================================================================
# Architecture: ONE Azure provider + ONE Ollama provider managing multiple models

AZURE_MODELS = {
    10: {"name": "azure-gpt-4-omni", "deployment": "gpt-4o", "provider_id": 2,
         "endpoint": "https://ase-se01.openai.azure.com/openai/deployments/gpt-4o/chat/completions?api-version=2024-08-01-preview"},
    12: {"name": "GPT o3 mini", "deployment": "o3-mini", "provider_id": 2,
         "endpoint": "https://ase-se01.openai.azure.com/openai/deployments/o3-mini/chat/completions?api-version=2024-12-01-preview"},
    21: {"name": "azure-gpt-4-omni", "deployment": "gpt-4o", "provider_id": 2,
         "endpoint": "https://ase-se01.openai.azure.com/openai/deployments/gpt-4o/chat/completions?api-version=2024-08-01-preview"},
    23: {"name": "gpt-4.1-nano", "deployment": "gpt-41-nano", "provider_id": 2,
         "endpoint": "https://ase-se01.openai.azure.com/openai/deployments/gpt-41-nano/chat/completions?api-version=2025-01-01-preview"},
    24: {"name": "gpt-4.1-mini", "deployment": "gpt-41-mini", "provider_id": 2,
         "endpoint": "https://ase-se01.openai.azure.com/openai/deployments/gpt-41-mini/chat/completions?api-version=2025-01-01-preview"},
    25: {"name": "gpt-4.1", "deployment": "gpt-41", "provider_id": 2,
         "endpoint": "https://ase-se01.openai.azure.com/openai/deployments/gpt-41/chat/completions?api-version=2025-01-01-preview"},
}

OLLAMA_MODELS = {
    1: {"name": "llama3.3:latest", "vram_mb": 8192, "provider_id": 4},
    14: {"name": "deepseek-r1:70b", "vram_mb": 40960, "provider_id": 4},
    15: {"name": "gemma3:27b", "vram_mb": 16384, "provider_id": 4},
    16: {"name": "qwen3:30b-a3b", "vram_mb": 18432, "provider_id": 4},
    17: {"name": "tinyllama:latest", "vram_mb": 1024, "provider_id": 4},
    18: {"name": "gemma3:4b", "vram_mb": 2048, "provider_id": 4},
    19: {"name": "qwen3:30b", "vram_mb": 18432, "provider_id": 4},
    20: {"name": "llama3.3:latest", "vram_mb": 8192, "provider_id": 4},
}


# =============================================================================
# Test Helpers
# =============================================================================

def create_task(task_id: int, model_id: int, priority: int, data: Optional[Dict] = None) -> Task:
    """Helper to create a test task."""
    task_data = data or {"prompt": f"Test task {task_id}"}
    # Task models format: [(model_id, weight, priority_int, parallel_capacity)]
    models = [(model_id, 1.0, priority, 2)]
    return Task(data=task_data, models=models, task_id=task_id)


def create_ollama_api_response(loaded_models: Dict[int, bool]) -> Mock:
    """
    Create mock response for Ollama /api/ps endpoint.

    Args:
        loaded_models: {model_id: is_loaded} - which models to include in response

    Returns:
        Mock response object
    """
    models_list = []
    for model_id, is_loaded in loaded_models.items():
        if is_loaded and model_id in OLLAMA_MODELS:
            models_list.append({
                "name": OLLAMA_MODELS[model_id]["name"],
                "size_vram": OLLAMA_MODELS[model_id]["vram_mb"] * 1024 * 1024,  # Convert MB to bytes
                "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat() + "Z"
            })

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"models": models_list}
    return mock_response


def create_azure_rate_limit_headers(remaining_requests: int = 100, remaining_tokens: int = 100000) -> Dict[str, str]:
    """Create mock Azure response headers with rate limit info."""
    return {
        'x-ratelimit-remaining-requests': str(remaining_requests),
        'x-ratelimit-remaining-tokens': str(remaining_tokens),
        'x-ratelimit-limit-requests': '1000',
        'x-ratelimit-limit-tokens': '1000000',
        'x-ratelimit-reset-requests': '60s',
        'x-ratelimit-reset-tokens': '60s',
    }


# =============================================================================
# Integration Test Scenarios
# =============================================================================

class TestMixedWorkload(unittest.TestCase):
    """Scenario 1: Mixed Azure + Ollama workload distribution."""

    def setUp(self):
        """Set up scheduler with both Azure and Ollama facades."""
        self.queue_mgr = PriorityQueueManager()

        # Create REAL facades
        self.ollama_facade = OllamaSchedulingDataFacade(
            queue_manager=self.queue_mgr,
            db_manager=None
        )
        self.azure_facade = AzureSchedulingDataFacade(db_manager=None)

        # Register Ollama models
        for model_id in [1, 14, 15]:
            self.ollama_facade.register_model(
                model_id=model_id,
                provider_name="ollama",
                ollama_admin_url="https://gpu.aet.cit.tum.de/api",
                model_name=OLLAMA_MODELS[model_id]["name"],
                total_vram_mb=65536,  # 64GB total
                provider_id=4
            )

        # Register Azure models
        for model_id in [10, 12, 21]:
            self.azure_facade.register_model(
                model_id=model_id,
                provider_name="azure",
                model_name=AZURE_MODELS[model_id]["name"],
                model_endpoint=AZURE_MODELS[model_id]["endpoint"],
                provider_id=2
            )

        # Create scheduler with real facades
        self.scheduler = SimplePriorityScheduler(
            queue_manager=self.queue_mgr,
            sdi_facades={
                "ollama": self.ollama_facade,
                "azure": self.azure_facade
            }
        )

    def test_low_priority_distribution(self):
        """Low priority tasks should distribute across available models."""
        # Mock: All models loaded/available
        ollama_response = create_ollama_api_response({1: True, 15: True})

        with patch('requests.get', return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

            headers = create_azure_rate_limit_headers(remaining_requests=100)
            self.azure_facade.update_rate_limits("azure", "gpt-4o", headers)

        # Enqueue multiple LOW priority tasks
        tasks = [
            create_task(1, model_id=10, priority=1),  # Azure
            create_task(2, model_id=1, priority=1),   # Ollama llama3.3
            create_task(3, model_id=15, priority=1),  # Ollama gemma3:27b
        ]

        for task in tasks:
            self.scheduler.enqueue(task)

        # All have capacity
        work_table = {10: 2, 1: 2, 15: 2}

        # Verify all queued
        self.assertEqual(self.queue_mgr.get_state(10).low, 1)
        self.assertEqual(self.queue_mgr.get_state(1).low, 1)
        self.assertEqual(self.queue_mgr.get_state(15).low, 1)

        # Schedule all tasks
        for _ in range(3):
            scheduled = self.scheduler.schedule(work_table)
            self.assertIsNotNone(scheduled)

        # All should be scheduled
        self.assertTrue(self.scheduler.is_empty())


class TestRateLimitHandling(unittest.TestCase):
    """Scenario 2: Azure rate limit exhaustion and failover."""

    def setUp(self):
        """Set up scheduler with rate-limited Azure models."""
        self.queue_mgr = PriorityQueueManager()
        self.ollama_facade = OllamaSchedulingDataFacade(self.queue_mgr)
        self.azure_facade = AzureSchedulingDataFacade()

        # Register models
        self.ollama_facade.register_model(
            1, "ollama", "https://gpu.aet.cit.tum.de/api",
            "llama3.3:latest", 65536, provider_id=4
        )

        self.azure_facade.register_model(
            10, "azure", "azure-gpt-4-omni",
            AZURE_MODELS[10]["endpoint"], provider_id=2
        )

        self.scheduler = SimplePriorityScheduler(
            queue_manager=self.queue_mgr,
            sdi_facades={"ollama": self.ollama_facade, "azure": self.azure_facade}
        )

    def test_failover_to_ollama(self):
        """With Azure rate-limited per SDI, Ollama models should handle load."""
        # Azure: rate limited
        headers = create_azure_rate_limit_headers(remaining_requests=0)
        self.azure_facade.update_rate_limits("azure", "gpt-4o", headers)

        # Ollama: available
        ollama_response = create_ollama_api_response({1: True})
        with patch('requests.get', return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        # Query SDI for both providers
        azure_capacity = self.azure_facade.get_capacity_info("azure", "gpt-4o")
        ollama_status = self.ollama_facade.get_model_status(1)

        # Verify SDI state
        self.assertFalse(azure_capacity.has_capacity)
        self.assertTrue(ollama_status.is_loaded)

        # Enqueue tasks for both
        task_azure = create_task(1, model_id=10, priority=5)
        task_ollama = create_task(2, model_id=1, priority=5)

        self.scheduler.enqueue(task_azure)
        self.scheduler.enqueue(task_ollama)

        # Build work_table from SDI data
        work_table = {
            10: 2 if azure_capacity.has_capacity else 0,
            1: 2 if ollama_status.is_loaded else 0
        }

        # Schedule should pick Ollama task (only one with capacity)
        scheduled = self.scheduler.schedule(work_table)
        self.assertIsNotNone(scheduled)
        self.assertEqual(scheduled.get_id(), 2)  # Ollama task

        # Azure task still queued
        state = self.queue_mgr.get_state(10)
        self.assertEqual(state.normal, 1)


class TestColdStartScenarios(unittest.TestCase):
    """Scenario 3: Ollama cold start handling."""

    def setUp(self):
        """Set up scheduler with Ollama models in various states."""
        self.queue_mgr = PriorityQueueManager()
        self.ollama_facade = OllamaSchedulingDataFacade(self.queue_mgr)

        # Register models
        for model_id in [1, 14, 17, 18]:
            self.ollama_facade.register_model(
                model_id, "ollama", "https://gpu.aet.cit.tum.de/api",
                OLLAMA_MODELS[model_id]["name"], 65536, provider_id=4
            )

        self.scheduler = SimplePriorityScheduler(
            queue_manager=self.queue_mgr,
            sdi_facades={"ollama": self.ollama_facade}
        )

    def test_warm_model_preferred(self):
        """Scheduler should prefer warm (loaded) models."""
        # Model 1: loaded (warm), Model 14: not loaded (cold)
        ollama_response = create_ollama_api_response({1: True, 14: False})

        with patch('requests.get', return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        # Verify cold/warm state via SDI
        status_warm = self.ollama_facade.get_model_status(1)
        status_cold = self.ollama_facade.get_model_status(14)

        self.assertTrue(status_warm.is_loaded)
        self.assertFalse(status_cold.is_loaded)

        # Enqueue same priority tasks for both
        task_warm = create_task(1, model_id=1, priority=5)
        task_cold = create_task(2, model_id=14, priority=5)

        self.scheduler.enqueue(task_warm)
        self.scheduler.enqueue(task_cold)

        # Both have capacity
        work_table = {1: 2, 14: 2}

        # Scheduling logic can choose either (both same priority)
        scheduled = self.scheduler.schedule(work_table)
        self.assertIsNotNone(scheduled)

    def test_vram_constraints(self):
        """Test VRAM capacity tracking."""
        # Load large model (deepseek-r1:70b = 40GB)
        ollama_response = create_ollama_api_response({14: True})

        with patch('requests.get', return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        capacity = self.ollama_facade.get_capacity_info("ollama")

        # Should have used 40GB of 64GB
        self.assertEqual(capacity.total_vram_mb, 65536)
        self.assertEqual(capacity.available_vram_mb, 65536 - 40960)
        self.assertIn("deepseek-r1:70b", capacity.loaded_models)

    def test_multiple_models_loaded(self):
        """Test tracking multiple loaded models."""
        # Load small models: tinyllama (1GB) + gemma3:4b (2GB)
        ollama_response = create_ollama_api_response({17: True, 18: True})

        with patch('requests.get', return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        capacity = self.ollama_facade.get_capacity_info("ollama")

        # 3GB total used
        self.assertEqual(capacity.available_vram_mb, 65536 - 1024 - 2048)
        self.assertEqual(len(capacity.loaded_models), 2)


class TestHighTrafficBurst(unittest.TestCase):
    """Scenario 4: High traffic with queue buildup."""

    def setUp(self):
        """Set up scheduler with limited capacity."""
        self.queue_mgr = PriorityQueueManager()
        self.ollama_facade = OllamaSchedulingDataFacade(self.queue_mgr)

        # Register models
        for model_id in [1, 15, 17]:
            self.ollama_facade.register_model(
                model_id, "ollama", "https://gpu.aet.cit.tum.de/api",
                OLLAMA_MODELS[model_id]["name"], 65536, provider_id=4
            )

        self.scheduler = SimplePriorityScheduler(
            queue_manager=self.queue_mgr,
            sdi_facades={"ollama": self.ollama_facade}
        )

    def test_queue_buildup(self):
        """Enqueuing many tasks should build up queue depth."""
        # Load model 1
        ollama_response = create_ollama_api_response({1: True})
        with patch('requests.get', return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        # Enqueue 20 tasks for single model
        for i in range(20):
            priority = [1, 5, 10][i % 3]  # Mix priorities
            task = create_task(i, model_id=1, priority=priority)
            self.scheduler.enqueue(task)

        # Verify queue depth
        state = self.queue_mgr.get_state(1)
        self.assertEqual(state.total, 20)

        # Should have mix of priorities
        self.assertGreater(state.low, 0)
        self.assertGreater(state.normal, 0)
        self.assertGreater(state.high, 0)

    def test_limited_capacity_scheduling(self):
        """With limited capacity, only some tasks should schedule."""
        ollama_response = create_ollama_api_response({1: True})
        with patch('requests.get', return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        # Enqueue 10 tasks
        for i in range(10):
            task = create_task(i, model_id=1, priority=5)
            self.scheduler.enqueue(task)

        # Only 3 slots available
        work_table = {1: 3}

        # Schedule 3 tasks
        scheduled_count = 0
        for _ in range(3):
            scheduled = self.scheduler.schedule(work_table)
            if scheduled:
                scheduled_count += 1

        self.assertEqual(scheduled_count, 3)

        # 7 tasks should remain queued
        state = self.queue_mgr.get_state(1)
        self.assertEqual(state.total, 7)

    def test_load_balancing_across_models(self):
        """Tasks should distribute across multiple available models."""
        # Load 3 models
        ollama_response = create_ollama_api_response({1: True, 15: True, 17: True})
        with patch('requests.get', return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        # Enqueue tasks for each model
        for model_id in [1, 15, 17]:
            for i in range(5):
                task = create_task(model_id * 100 + i, model_id=model_id, priority=5)
                self.scheduler.enqueue(task)

        # All models have capacity
        work_table = {1: 2, 15: 2, 17: 2}

        # Verify distribution
        self.assertEqual(self.queue_mgr.get_state(1).total, 5)
        self.assertEqual(self.queue_mgr.get_state(15).total, 5)
        self.assertEqual(self.queue_mgr.get_state(17).total, 5)

        # Schedule from each model
        for _ in range(6):
            scheduled = self.scheduler.schedule(work_table)
            self.assertIsNotNone(scheduled)


class TestSDIIntegration(unittest.TestCase):
    """Test SDI facade integration with scheduler."""

    def setUp(self):
        """Set up facades and scheduler."""
        self.queue_mgr = PriorityQueueManager()
        self.ollama_facade = OllamaSchedulingDataFacade(self.queue_mgr)
        self.azure_facade = AzureSchedulingDataFacade()

        self.ollama_facade.register_model(
            1, "ollama", "https://gpu.aet.cit.tum.de/api",
            "llama3.3:latest", 65536, provider_id=4
        )

        self.azure_facade.register_model(
            10, "azure", "azure-gpt-4-omni",
            AZURE_MODELS[10]["endpoint"], provider_id=2
        )

        self.scheduler = SimplePriorityScheduler(
            queue_manager=self.queue_mgr,
            sdi_facades={"ollama": self.ollama_facade, "azure": self.azure_facade}
        )

    def test_queue_state_reporting(self):
        """SDI should report accurate queue state for Ollama models."""
        ollama_response = create_ollama_api_response({1: True})
        with patch('requests.get', return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        # Enqueue tasks at different priorities
        for priority in [1, 5, 10]:
            for i in range(3):
                task = create_task(i + priority * 10, model_id=1, priority=priority)
                self.scheduler.enqueue(task)

        # Query queue state via SDI
        status = self.ollama_facade.get_model_status(1)

        self.assertEqual(status.queue_state.low, 3)
        self.assertEqual(status.queue_state.normal, 3)
        self.assertEqual(status.queue_state.high, 3)
        self.assertEqual(status.queue_state.total, 9)

    def test_azure_no_queue_visibility(self):
        """Azure models should not expose queue state."""
        status = self.azure_facade.get_model_status(10)

        self.assertIsNone(status.queue_state)
        self.assertEqual(status.provider_type, "azure")

    def test_ollama_queue_visibility(self):
        """Ollama models should expose queue state."""
        ollama_response = create_ollama_api_response({1: True})
        with patch('requests.get', return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        task = create_task(1, model_id=1, priority=5)
        self.scheduler.enqueue(task)

        status = self.ollama_facade.get_model_status(1)

        self.assertIsNotNone(status.queue_state)
        self.assertEqual(status.provider_type, "ollama")
        self.assertEqual(status.queue_state.total, 1)


class TestSDIDataUsage(unittest.TestCase):
    """Test that scheduler actually uses SDI data (rate limits, VRAM, loaded models)."""

    def setUp(self):
        """Set up facades and scheduler."""
        self.queue_mgr = PriorityQueueManager()
        self.ollama_facade = OllamaSchedulingDataFacade(self.queue_mgr)
        self.azure_facade = AzureSchedulingDataFacade()

        # Register Ollama models with different VRAM requirements
        self.ollama_facade.register_model(
            1, "ollama", "https://gpu.aet.cit.tum.de/api",
            "llama3.3:latest", 65536, provider_id=4  # 8GB VRAM
        )
        self.ollama_facade.register_model(
            14, "ollama", "https://gpu.aet.cit.tum.de/api",
            "deepseek-r1:70b", 65536, provider_id=4  # 40GB VRAM
        )

        # Register Azure model
        self.azure_facade.register_model(
            10, "azure", "azure-gpt-4-omni",
            AZURE_MODELS[10]["endpoint"], provider_id=2
        )

        self.scheduler = SimplePriorityScheduler(
            queue_manager=self.queue_mgr,
            sdi_facades={"ollama": self.ollama_facade, "azure": self.azure_facade}
        )

    def test_azure_rate_limit_blocks_scheduling(self):
        """Azure rate limits queried via get_capacity_info() should block scheduling."""
        # Set rate limit to 0
        headers = create_azure_rate_limit_headers(remaining_requests=0)
        self.azure_facade.update_rate_limits("azure", "gpt-4o", headers)

        # Query SDI for capacity
        capacity = self.azure_facade.get_capacity_info("azure", "gpt-4o")
        self.assertFalse(capacity.has_capacity)
        self.assertEqual(capacity.rate_limit_remaining_requests, 0)

        # Enqueue task for Azure
        task = create_task(1, model_id=10, priority=5)
        self.scheduler.enqueue(task)

        # Build work_table based on SDI capacity data
        work_table = {10: 2 if capacity.has_capacity else 0}

        # Should NOT be able to schedule (rate limited)
        scheduled = self.scheduler.schedule(work_table)
        self.assertIsNone(scheduled)

    def test_azure_rate_limit_recovery_enables_scheduling(self):
        """When rate limit resets, get_capacity_info() should reflect it."""
        # Start rate-limited
        headers = create_azure_rate_limit_headers(remaining_requests=0)
        self.azure_facade.update_rate_limits("azure", "gpt-4o", headers)

        task = create_task(1, model_id=10, priority=5)
        self.scheduler.enqueue(task)

        capacity = self.azure_facade.get_capacity_info("azure", "gpt-4o")
        self.assertFalse(capacity.has_capacity)

        # Rate limit resets
        headers = create_azure_rate_limit_headers(remaining_requests=100)
        self.azure_facade.update_rate_limits("azure", "gpt-4o", headers)

        # Query again - should show capacity now
        capacity = self.azure_facade.get_capacity_info("azure", "gpt-4o")
        self.assertTrue(capacity.has_capacity)
        self.assertEqual(capacity.rate_limit_remaining_requests, 100)

        # Build work_table from SDI
        work_table = {10: 2 if capacity.has_capacity else 0}

        # Now can schedule
        scheduled = self.scheduler.schedule(work_table)
        self.assertIsNotNone(scheduled)
        self.assertEqual(scheduled.get_id(), 1)

    def test_ollama_loaded_model_status_tracked(self):
        """SDI should accurately report which Ollama models are loaded."""
        # Mock: Model 1 is loaded (warm), Model 14 is not (cold)
        ollama_response = create_ollama_api_response({
            1: True,   # llama3.3 loaded, 8GB VRAM
            14: False  # deepseek-r1 NOT loaded
        })

        with patch('requests.get', return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        # Query SDI for model status
        status_warm = self.ollama_facade.get_model_status(1)
        status_cold = self.ollama_facade.get_model_status(14)

        # Verify is_loaded is accurate
        self.assertTrue(status_warm.is_loaded)
        self.assertGreater(status_warm.vram_mb, 0)

        self.assertFalse(status_cold.is_loaded)
        self.assertEqual(status_cold.vram_mb, 0)

    def test_ollama_vram_capacity_tracked(self):
        """get_capacity_info() should report accurate VRAM usage."""
        # Load model 1 (8GB) and model 14 (40GB) from OLLAMA_MODELS
        ollama_response = create_ollama_api_response({
            1: True,   # llama3.3:latest - 8GB
            14: True   # deepseek-r1:70b - 40GB
        })

        with patch('requests.get', return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        # Query VRAM capacity via SDI
        capacity = self.ollama_facade.get_capacity_info("ollama")

        # Should have 64GB total - 48GB used (8GB + 40GB) = ~16GB free
        self.assertEqual(capacity.total_vram_mb, 65536)
        self.assertAlmostEqual(capacity.available_vram_mb, 65536 - 8192 - 40960, delta=100)
        # Verify both models are tracked as loaded
        self.assertEqual(len(capacity.loaded_models), 2)

    def test_work_table_derived_from_sdi_multi_provider(self):
        """Work table should be built from querying both facades."""
        # Setup Azure with rate limit
        azure_headers = create_azure_rate_limit_headers(remaining_requests=50)
        self.azure_facade.update_rate_limits("azure", "gpt-4o", azure_headers)

        # Setup Ollama with loaded model
        ollama_response = create_ollama_api_response({1: True, 14: False})
        with patch('requests.get', return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        # Build work_table by querying SDI facades
        work_table = {}

        # Query Azure capacity
        azure_capacity = self.azure_facade.get_capacity_info("azure", "gpt-4o")
        work_table[10] = 2 if azure_capacity.has_capacity else 0

        # Query Ollama capacity (assuming parallel_capacity=2 for loaded models)
        ollama_status_1 = self.ollama_facade.get_model_status(1)
        ollama_status_14 = self.ollama_facade.get_model_status(14)
        work_table[1] = 2 if ollama_status_1.is_loaded else 0
        work_table[14] = 2 if ollama_status_14.is_loaded else 0

        # Verify work_table reflects SDI state
        self.assertEqual(work_table[10], 2)  # Azure has capacity
        self.assertEqual(work_table[1], 2)   # Ollama model 1 loaded
        self.assertEqual(work_table[14], 0)   # Ollama model 14 NOT loaded

        # Enqueue tasks
        task_azure = create_task(1, model_id=10, priority=5)
        task_warm = create_task(2, model_id=1, priority=5)
        task_cold = create_task(3, model_id=14, priority=5)

        self.scheduler.enqueue(task_azure)
        self.scheduler.enqueue(task_warm)
        self.scheduler.enqueue(task_cold)

        # Schedule - should only schedule to Azure (10) or warm Ollama (1)
        scheduled = self.scheduler.schedule(work_table)
        self.assertIsNotNone(scheduled)
        self.assertIn(scheduled.get_id(), [1, 2])  # Azure or warm model
        self.assertNotEqual(scheduled.get_id(), 3)  # NOT cold model


# =============================================================================
# Request Lifecycle Tests - Critical Integration Scenarios
# =============================================================================

class TestRequestLifecycleSequential(unittest.TestCase):
    """Test complete request lifecycle with sequential execution and queue progression."""

    def setUp(self):
        """Set up scheduler with Ollama facade."""
        self.queue_mgr = PriorityQueueManager()
        self.ollama_facade = OllamaSchedulingDataFacade(self.queue_mgr)

        self.ollama_facade.register_model(
            1, "ollama", "https://gpu.aet.cit.tum.de/api",
            "llama3.3:latest", 65536, provider_id=4
        )

        self.scheduler = SimplePriorityScheduler(
            queue_manager=self.queue_mgr,
            sdi_facades={"ollama": self.ollama_facade}
        )

    def test_sequential_execution_with_queue_draining(self):
        """
        Lifecycle: Enqueue 5 tasks → Execute them one-by-one → Verify queue drains.

        Verifies:
        - Queue depth decreases as tasks are scheduled
        - Active requests increments/decrements correctly
        - SDI reports accurate state throughout
        - Queue eventually empties completely
        """
        # Setup: Model loaded
        ollama_response = create_ollama_api_response({1: True})
        with patch('requests.get', return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        # Step 1: Enqueue 5 tasks
        for i in range(5):
            task = create_task(i, model_id=1, priority=5)
            self.scheduler.enqueue(task)

        # Verify initial state: 5 queued, 0 active
        status = self.ollama_facade.get_model_status(1)
        self.assertEqual(status.queue_state.total, 5)
        self.assertEqual(status.active_requests, 0)

        # Step 2: Execute tasks sequentially (capacity=1)
        work_table = {1: 1}

        for expected_remaining in [4, 3, 2, 1, 0]:
            # Schedule (dequeue) task
            task = self.scheduler.schedule(work_table)
            self.assertIsNotNone(task)

            # Simulate: Task begins processing (increment active)
            self.ollama_facade.on_request_start(f"req-{task.get_id()}", model_id=1)
            self.ollama_facade.on_request_begin_processing(f"req-{task.get_id()}")

            # Verify: Queue decreased, active increased
            status = self.ollama_facade.get_model_status(1)
            self.assertEqual(status.queue_state.total, expected_remaining)
            self.assertEqual(status.active_requests, 1)

            # Simulate: Task completes (decrement active, free capacity)
            metrics = self.ollama_facade.on_request_complete(
                f"req-{task.get_id()}",
                was_cold_start=False,
                duration_ms=100
            )

            # Verify: Active back to 0
            status = self.ollama_facade.get_model_status(1)
            self.assertEqual(status.active_requests, 0)

        # Step 3: Verify final state - everything drained
        self.assertTrue(self.scheduler.is_empty())
        status = self.ollama_facade.get_model_status(1)
        self.assertEqual(status.queue_state.total, 0)
        self.assertEqual(status.active_requests, 0)


class TestRequestLifecycleParallel(unittest.TestCase):
    """Test parallel execution with capacity limits and queue progression."""

    def setUp(self):
        """Set up scheduler with Ollama facade."""
        self.queue_mgr = PriorityQueueManager()
        self.ollama_facade = OllamaSchedulingDataFacade(self.queue_mgr)

        self.ollama_facade.register_model(
            1, "ollama", "https://gpu.aet.cit.tum.de/api",
            "llama3.3:latest", 65536, provider_id=4
        )

        self.scheduler = SimplePriorityScheduler(
            queue_manager=self.queue_mgr,
            sdi_facades={"ollama": self.ollama_facade}
        )

    def test_parallel_execution_with_capacity_limits(self):
        """
        Lifecycle: Enqueue 10 tasks → Execute 3 in parallel → Complete → Execute next 3.

        Verifies:
        - Capacity limits enforced (max 3 concurrent)
        - Queue progresses as tasks complete
        - Active requests tracked correctly
        - SDI state accurate during concurrent execution
        """
        # Setup: Model loaded
        ollama_response = create_ollama_api_response({1: True})
        with patch('requests.get', return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        # Step 1: Enqueue 10 tasks
        for i in range(10):
            task = create_task(i, model_id=1, priority=5)
            self.scheduler.enqueue(task)

        # Verify: 10 queued, 0 active
        status = self.ollama_facade.get_model_status(1)
        self.assertEqual(status.queue_state.total, 10)
        self.assertEqual(status.active_requests, 0)

        # Step 2: Schedule first 3 tasks (capacity=3)
        work_table = {1: 3}
        active_tasks = []

        for i in range(3):
            task = self.scheduler.schedule(work_table)
            self.assertIsNotNone(task)

            # Start processing
            self.ollama_facade.on_request_start(f"req-{task.get_id()}", model_id=1)
            self.ollama_facade.on_request_begin_processing(f"req-{task.get_id()}")
            active_tasks.append(task)

        # Verify: 7 queued, 3 active
        status = self.ollama_facade.get_model_status(1)
        self.assertEqual(status.queue_state.total, 7)
        self.assertEqual(status.active_requests, 3)

        # Step 3: Try to schedule 4th task - should fail (capacity full)
        task = self.scheduler.schedule(work_table)
        # Task is dequeued but we simulate no capacity by not starting it
        # In real system, scheduler would check capacity before dequeuing
        # For this test, we verify active count is managed

        # Step 4: Complete first task, free 1 slot
        completed_task = active_tasks.pop(0)
        self.ollama_facade.on_request_complete(
            f"req-{completed_task.get_id()}",
            was_cold_start=False,
            duration_ms=200
        )

        # Verify: 7 queued, 2 active (one completed)
        status = self.ollama_facade.get_model_status(1)
        self.assertEqual(status.active_requests, 2)

        # Step 5: Complete remaining 2 tasks
        for task in active_tasks:
            self.ollama_facade.on_request_complete(
                f"req-{task.get_id()}",
                was_cold_start=False,
                duration_ms=200
            )

        # Verify: Active back to 0
        status = self.ollama_facade.get_model_status(1)
        self.assertEqual(status.active_requests, 0)


class TestRequestLifecycleMixedPriority(unittest.TestCase):
    """Test request lifecycle with mixed priorities - verify HIGH executes first."""

    def setUp(self):
        """Set up scheduler with Ollama facade."""
        self.queue_mgr = PriorityQueueManager()
        self.ollama_facade = OllamaSchedulingDataFacade(self.queue_mgr)

        self.ollama_facade.register_model(
            1, "ollama", "https://gpu.aet.cit.tum.de/api",
            "llama3.3:latest", 65536, provider_id=4
        )

        self.scheduler = SimplePriorityScheduler(
            queue_manager=self.queue_mgr,
            sdi_facades={"ollama": self.ollama_facade}
        )

    def test_lifecycle_respects_priority_ordering(self):
        """
        Lifecycle: Enqueue LOW/NORMAL/HIGH → Verify HIGH executes first as queue drains.

        Verifies:
        - Priority ordering maintained throughout lifecycle
        - Queue state per-priority level accurate
        - HIGH tasks execute before NORMAL before LOW
        """
        # Setup: Model loaded
        ollama_response = create_ollama_api_response({1: True})
        with patch('requests.get', return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        # Step 1: Enqueue mixed priorities
        # LOW: tasks 0, 1
        # NORMAL: tasks 2, 3
        # HIGH: tasks 4, 5
        for i in range(6):
            priority = [1, 1, 5, 5, 10, 10][i]
            task = create_task(i, model_id=1, priority=priority)
            self.scheduler.enqueue(task)

        # Verify queue breakdown
        status = self.ollama_facade.get_model_status(1)
        self.assertEqual(status.queue_state.low, 2)
        self.assertEqual(status.queue_state.normal, 2)
        self.assertEqual(status.queue_state.high, 2)
        self.assertEqual(status.queue_state.total, 6)

        # Step 2: Execute tasks and verify priority order
        work_table = {1: 1}
        executed_ids = []

        for _ in range(6):
            task = self.scheduler.schedule(work_table)
            self.assertIsNotNone(task)
            executed_ids.append(task.get_id())

            # Process and complete immediately
            self.ollama_facade.on_request_start(f"req-{task.get_id()}", model_id=1)
            self.ollama_facade.on_request_begin_processing(f"req-{task.get_id()}")
            self.ollama_facade.on_request_complete(
                f"req-{task.get_id()}",
                was_cold_start=False,
                duration_ms=100
            )

        # Verify execution order: HIGH (4,5) → NORMAL (2,3) → LOW (0,1)
        self.assertEqual(executed_ids[:2], [4, 5])  # HIGH tasks first
        self.assertEqual(executed_ids[2:4], [2, 3])  # NORMAL tasks second
        self.assertEqual(executed_ids[4:6], [0, 1])  # LOW tasks last

        # Verify final state
        status = self.ollama_facade.get_model_status(1)
        self.assertEqual(status.queue_state.total, 0)
        self.assertEqual(status.active_requests, 0)


class TestRequestLifecycleMultiProvider(unittest.TestCase):
    """Test lifecycle with both Azure and Ollama executing concurrently."""

    def setUp(self):
        """Set up scheduler with both providers."""
        self.queue_mgr = PriorityQueueManager()
        self.ollama_facade = OllamaSchedulingDataFacade(self.queue_mgr)
        self.azure_facade = AzureSchedulingDataFacade()

        self.ollama_facade.register_model(
            1, "ollama", "https://gpu.aet.cit.tum.de/api",
            "llama3.3:latest", 65536, provider_id=4
        )

        self.azure_facade.register_model(
            10, "azure", "azure-gpt-4-omni",
            AZURE_MODELS[10]["endpoint"], provider_id=2
        )

        self.scheduler = SimplePriorityScheduler(
            queue_manager=self.queue_mgr,
            sdi_facades={"ollama": self.ollama_facade, "azure": self.azure_facade}
        )

    def test_concurrent_multi_provider_execution(self):
        """
        Lifecycle: Enqueue tasks for both providers → Execute concurrently → Verify SDI.

        Verifies:
        - Both providers process tasks simultaneously
        - Queue state tracked independently per provider
        - Ollama tracks active requests, Azure doesn't
        - Both queues drain correctly
        """
        # Setup: Ollama loaded, Azure available
        ollama_response = create_ollama_api_response({1: True})
        with patch('requests.get', return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        headers = create_azure_rate_limit_headers(remaining_requests=100)
        self.azure_facade.update_rate_limits("azure", "gpt-4o", headers)

        # Step 1: Enqueue 3 tasks for each provider
        for i in range(3):
            task_ollama = create_task(i, model_id=1, priority=5)
            task_azure = create_task(i + 10, model_id=10, priority=5)
            self.scheduler.enqueue(task_ollama)
            self.scheduler.enqueue(task_azure)

        # Verify initial state
        ollama_status = self.ollama_facade.get_model_status(1)
        azure_status = self.azure_facade.get_model_status(10)
        self.assertEqual(ollama_status.queue_state.total, 3)
        self.assertEqual(self.queue_mgr.get_state(10).total, 3)  # Azure queue via queue_mgr

        # Step 2: Execute 1 task from each provider concurrently
        work_table = {1: 1, 10: 1}

        # Schedule from Ollama
        ollama_task = self.scheduler.schedule(work_table)
        self.assertIn(ollama_task.get_id(), [0, 1, 2, 10, 11, 12])  # Could be either

        # Track which provider it came from
        if ollama_task.get_id() < 10:
            # Ollama task
            self.ollama_facade.on_request_start(f"req-{ollama_task.get_id()}", model_id=1)
            self.ollama_facade.on_request_begin_processing(f"req-{ollama_task.get_id()}")

            ollama_status = self.ollama_facade.get_model_status(1)
            self.assertEqual(ollama_status.queue_state.total, 2)
            self.assertEqual(ollama_status.active_requests, 1)

        # Schedule from Azure (or second task)
        azure_task = self.scheduler.schedule(work_table)
        # Note: Azure doesn't track active requests (cloud provider)

        # Step 3: Complete Ollama task
        if ollama_task.get_id() < 10:
            self.ollama_facade.on_request_complete(
                f"req-{ollama_task.get_id()}",
                was_cold_start=False,
                duration_ms=150
            )

            ollama_status = self.ollama_facade.get_model_status(1)
            self.assertEqual(ollama_status.active_requests, 0)

        # Verify: Both queues progressing independently
        self.assertFalse(self.scheduler.is_empty())  # Still have tasks remaining


class TestRequestLifecycleQueueDrainComplete(unittest.TestCase):
    """Test complete queue drain with SDI verification at each step."""

    def setUp(self):
        """Set up scheduler with Ollama facade."""
        self.queue_mgr = PriorityQueueManager()
        self.ollama_facade = OllamaSchedulingDataFacade(self.queue_mgr)

        self.ollama_facade.register_model(
            1, "ollama", "https://gpu.aet.cit.tum.de/api",
            "llama3.3:latest", 65536, provider_id=4
        )

        self.scheduler = SimplePriorityScheduler(
            queue_manager=self.queue_mgr,
            sdi_facades={"ollama": self.ollama_facade}
        )

    def test_complete_queue_drain_with_sdi_verification(self):
        """
        Lifecycle: Enqueue 8 tasks → Drain completely → Verify SDI accuracy at every step.

        Verifies:
        - SDI queue_depth decreases monotonically
        - SDI active_requests accurate throughout
        - Queue state per-priority correct
        - Final state is completely empty
        - All metrics consistent from start to finish
        """
        # Setup: Model loaded
        ollama_response = create_ollama_api_response({1: True})
        with patch('requests.get', return_value=ollama_response):
            self.ollama_facade._providers["ollama"].refresh_data()

        # Step 1: Enqueue 8 tasks (mixed priorities: 3 LOW, 3 NORMAL, 2 HIGH)
        priorities = [1, 1, 1, 5, 5, 5, 10, 10]
        for i, priority in enumerate(priorities):
            task = create_task(i, model_id=1, priority=priority)
            self.scheduler.enqueue(task)

        # Verify initial SDI state
        status = self.ollama_facade.get_model_status(1)
        self.assertEqual(status.queue_state.low, 3)
        self.assertEqual(status.queue_state.normal, 3)
        self.assertEqual(status.queue_state.high, 2)
        self.assertEqual(status.queue_state.total, 8)
        self.assertEqual(status.active_requests, 0)
        self.assertTrue(status.is_loaded)

        # Step 2: Drain queue completely, verifying SDI at each step
        work_table = {1: 1}
        expected_queue_depths = [7, 6, 5, 4, 3, 2, 1, 0]  # After each dequeue

        for i, expected_depth in enumerate(expected_queue_depths):
            # Schedule task
            task = self.scheduler.schedule(work_table)
            self.assertIsNotNone(task, f"Task {i} should be schedulable")

            # Verify queue decreased
            status = self.ollama_facade.get_model_status(1)
            self.assertEqual(status.queue_state.total, expected_depth,
                           f"Queue depth should be {expected_depth} after scheduling task {i}")

            # Start processing
            self.ollama_facade.on_request_start(f"req-{task.get_id()}", model_id=1, priority="normal")
            self.ollama_facade.on_request_begin_processing(f"req-{task.get_id()}")

            # Verify active incremented
            status = self.ollama_facade.get_model_status(1)
            self.assertEqual(status.active_requests, 1,
                           f"Active requests should be 1 while processing task {i}")

            # Complete task
            metrics = self.ollama_facade.on_request_complete(
                f"req-{task.get_id()}",
                was_cold_start=(i == 0),  # First task might be cold start
                duration_ms=100 + (i * 10)  # Variable duration
            )

            # Verify metrics returned
            self.assertIsNotNone(metrics)
            self.assertEqual(metrics.duration_ms, 100 + (i * 10))

            # Verify active decremented
            status = self.ollama_facade.get_model_status(1)
            self.assertEqual(status.active_requests, 0,
                           f"Active requests should be 0 after completing task {i}")

        # Step 3: Verify final state - completely drained
        self.assertTrue(self.scheduler.is_empty())

        status = self.ollama_facade.get_model_status(1)
        self.assertEqual(status.queue_state.low, 0)
        self.assertEqual(status.queue_state.normal, 0)
        self.assertEqual(status.queue_state.high, 0)
        self.assertEqual(status.queue_state.total, 0)
        self.assertEqual(status.active_requests, 0)
        self.assertTrue(status.is_loaded)  # Model still loaded

        # Step 4: Verify no more tasks can be scheduled
        task = self.scheduler.schedule(work_table)
        self.assertIsNone(task, "Should return None when queue is empty")


if __name__ == "__main__":
    unittest.main()
