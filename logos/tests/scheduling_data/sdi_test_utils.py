"""
Shared test fixtures and helpers for SDI (Scheduling Data Interface) tests.
"""

import datetime
from typing import Dict, List, Tuple, Optional
from unittest.mock import Mock


class Task:
    """Simple task object for testing queue operations."""

    def __init__(self, data: dict, models: List[Tuple[int, float, int, int]], task_id: int) -> None:
        self.data = data
        self.models = models
        self.__id = task_id

    def get_id(self):
        return self.__id

    def get_best_model_id(self):
        if len(self.models) == 0:
            return None
        return self.models[0][0]


# Realistic model metadata used across SDI tests (inputs to facades)
AZURE_MODELS = {
    10: {
        "name": "azure-gpt-4-omni",
        "deployment": "gpt-4o",
        "provider_id": 2,
        "endpoint": "https://ase-se01.openai.azure.com/openai/deployments/gpt-4o/chat/completions?api-version=2024-08-01-preview",
    },
    12: {
        "name": "azure-gpt-4-omni",
        "deployment": "gpt-4o",
        "provider_id": 2,
        "endpoint": "https://ase-se01.openai.azure.com/openai/deployments/gpt-4o/chat/completions?api-version=2024-08-01-preview",
    },
    21: {
        "name": "azure-gpt-4-omni",
        "deployment": "gpt-4o",
        "provider_id": 2,
        "endpoint": "https://ase-se01.openai.azure.com/openai/deployments/gpt-4o/chat/completions?api-version=2024-08-01-preview",
    },
    23: {
        "name": "gpt-4.1-nano",
        "deployment": "gpt-41-nano",
        "provider_id": 2,
        "endpoint": "https://ase-se01.openai.azure.com/openai/deployments/gpt-41-nano/chat/completions?api-version=2025-01-01-preview",
    },
    24: {
        "name": "gpt-4.1-mini",
        "deployment": "gpt-41-mini",
        "provider_id": 2,
        "endpoint": "https://ase-se01.openai.azure.com/openai/deployments/gpt-41-mini/chat/completions?api-version=2025-01-01-preview",
    },
    25: {
        "name": "gpt-4.1",
        "deployment": "gpt-41",
        "provider_id": 2,
        "endpoint": "https://ase-se01.openai.azure.com/openai/deployments/gpt-41/chat/completions?api-version=2025-01-01-preview",
    },
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


def create_task(task_id: int, model_id: int, priority: int, data: Optional[Dict] = None) -> Task:
    """Create a scheduler Task with a single model entry."""
    task_data = data or {"prompt": f"Test task {task_id}"}
    models = [(model_id, 1.0, priority, 2)]  # (model_id, weight, priority, parallel_capacity)
    return Task(data=task_data, models=models, task_id=task_id)


# Ollama /api/ps payload + optional Mock wrapper
def build_ollama_ps_payload(loaded_models: Dict[int, bool]) -> Dict:
    """
    Build JSON payload for /api/ps showing which models are loaded.

    Args:
        loaded_models: Mapping of model_id -> bool indicating if loaded.
    """
    models_list = []
    now = datetime.datetime.now(datetime.timezone.utc)
    for model_id, is_loaded in loaded_models.items():
        if is_loaded and model_id in OLLAMA_MODELS:
            models_list.append(
                {
                    "name": OLLAMA_MODELS[model_id]["name"],
                    "size_vram": OLLAMA_MODELS[model_id]["vram_mb"] * 1024 * 1024,
                    "expires_at": (now + datetime.timedelta(minutes=30)).isoformat() + "Z",
                }
            )
    return {"models": models_list}


def create_ollama_api_ps_response(loaded_models: Dict[int, bool]) -> Mock:
    """Return a Mock requests.get response for /api/ps using build_ollama_ps_payload()."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = build_ollama_ps_payload(loaded_models)
    return mock_response


def create_azure_rate_limit_headers(remaining_requests: int = 100, remaining_tokens: int = 100000) -> Dict[str, str]:
    """Create mock Azure response headers with rate limit info."""
    return {
        "x-ratelimit-remaining-requests": str(remaining_requests),
        "x-ratelimit-remaining-tokens": str(remaining_tokens),
        "x-ratelimit-limit-requests": "1000",
        "x-ratelimit-limit-tokens": "1000000",
        "x-ratelimit-reset-requests": "60s",
        "x-ratelimit-reset-tokens": "60s",
    }
