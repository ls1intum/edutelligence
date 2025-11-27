"""
Scheduling Data Interface (SDI) - Public API

Provides type-safe facades for accessing scheduling data from Ollama and Azure providers.

Architecture:
- OllamaSchedulingDataFacade: Type-safe facade for Ollama providers
- AzureSchedulingDataFacade: Type-safe facade for Azure providers
- OllamaDataProvider: Queries /api/ps for VRAM and load status
- AzureDataProvider: Tracks per-deployment rate limits from response headers

Usage (Ollama):
    from logos.sdi import OllamaSchedulingDataFacade
    from logos.scheduling.priority_queue_manager import PriorityQueueManager

    # Initialize
    queue_manager = PriorityQueueManager()
    facade = OllamaSchedulingDataFacade(queue_manager, db_manager=db_manager)

    # Register Ollama model
    facade.register_model(
        model_id=1,
        provider_name='openwebui',
        ollama_admin_url='http://gpu-vm-1.internal:11434',
        model_name='llama3.3:latest',
        total_vram_mb=49152  # 48GB
    )

    # Query for scheduling decisions (returns ModelStatus dataclass)
    status = facade.get_model_status(1)
    if status.is_loaded and status.queue_depth < 3:
        # Good candidate: warm and not overloaded
        ...

    # Track request lifecycle
    facade.on_request_start('req-123', model_id=1, priority='high')
    # ... process request ...
    metrics = facade.on_request_complete('req-123', was_cold_start=False, duration_ms=250)

Usage (Azure):
    from logos.sdi import AzureSchedulingDataFacade

    # Initialize
    facade = AzureSchedulingDataFacade(db_manager)

    # Register Azure model
    facade.register_model(
        model_id=10,
        provider_name='azure',
        model_name='gpt-4',
        model_endpoint='https://my.openai.azure.com/openai/deployments/gpt-4o/chat/completions'
    )

    # Get capacity info (returns AzureCapacity dataclass)
    capacity = facade.get_capacity_info('azure', 'gpt-4o')
    if capacity.has_capacity:
        # Send request
        ...

    # Update rate limits after API call
    facade.update_rate_limits('azure', 'gpt-4o', response.headers)
"""

from .ollama_facade import OllamaSchedulingDataFacade
from .azure_facade import AzureSchedulingDataFacade
from .providers import (
    OllamaDataProvider,
    AzureDataProvider,
    extract_azure_deployment_name
)
from .models import ModelStatus, OllamaCapacity, AzureCapacity, RequestMetrics

# Public API
__all__ = [
    # Facades
    'OllamaSchedulingDataFacade',
    'AzureSchedulingDataFacade',

    # Provider implementations
    'OllamaDataProvider',
    'AzureDataProvider',
    'extract_azure_deployment_name',

    # Dataclasses
    'ModelStatus',
    'OllamaCapacity',
    'AzureCapacity',
    'RequestMetrics',
]

__version__ = '1.0.0'
