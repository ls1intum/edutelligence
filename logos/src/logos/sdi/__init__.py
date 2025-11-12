"""
Scheduling Data Interface (SDI) - Public API

Provides a unified facade for accessing scheduling data from heterogeneous providers.
Uses /api/ps for Ollama providers and rate limit headers for cloud providers.

Architecture:
- SchedulingDataFacade: Unified entry point for schedulers
- SchedulingDataProvider: Interface implemented by all providers
- OllamaDataProvider: Queries /api/ps for VRAM and load status
- CloudDataProvider: Tracks rate limits from response headers
- AzureDataProvider: Azure-specific implementation

Usage:
    from logos.sdi import SchedulingDataFacade

    # Initialize
    facade = SchedulingDataFacade(db_manager)

    # Register Ollama model
    facade.register_model(
        model_id=1,
        provider_name='openwebui',
        provider_type='ollama',
        model_name='llama3.3:latest',
        ollama_admin_url='',  # TODO: Add internal Ollama endpoint (e.g., 'http://gpu-vm-1.internal:11434')
        total_vram_mb=49152  # 48GB
    )

    # Register Azure model
    facade.register_model(
        model_id=10,
        provider_name='azure',
        provider_type='cloud',
        model_name='azure-gpt-4-omni'
    )

    # Query for scheduling decisions
    status = facade.get_model_status(1)
    if not status['cold_start_predicted']:
        # Schedule to this model
        ...

    # Track request lifecycle
    facade.on_request_start('req-123', model_id=1, priority='high')
    # ... process request ...
    metrics = facade.on_request_complete('req-123', was_cold_start=False, duration_ms=250)

    # Query provider capacity
    capacity = facade.get_provider_capacity('openwebui')
    if capacity['available_vram_mb'] > 4096:
        # Sufficient VRAM for new model
        ...
"""

from .facade import SchedulingDataFacade
from .provider_interface import SchedulingDataProvider
from .providers import (
    OllamaDataProvider,
    CloudDataProvider,
    AzureDataProvider
)
from .models import ModelStatus, OllamaCapacity, CloudCapacity, RequestMetrics

# Public API (schedulers only need SchedulingDataFacade)
__all__ = [
    'SchedulingDataFacade',
    'SchedulingDataProvider',
    'OllamaDataProvider',
    'CloudDataProvider',
    'AzureDataProvider',
    'ModelStatus',
    'OllamaCapacity',
    'CloudCapacity',
    'RequestMetrics',
]

__version__ = '1.0.0'
