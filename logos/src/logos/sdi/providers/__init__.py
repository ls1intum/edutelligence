"""
Scheduling Data Provider Implementations.

Concrete implementations of scheduling data providers:
- OllamaDataProvider: Queries Ollama /api/ps for VRAM and model loading data
- AzureDataProvider: Tracks Azure OpenAI rate limits from response headers

Provider implementations are internal to SDI. Users should use the facade classes
(OllamaSchedulingDataFacade, CloudDataFacade) instead of directly instantiating providers.
"""

from .ollama_provider import OllamaDataProvider
from .azure_provider import AzureDataProvider, extract_azure_deployment_name

__all__ = [
    'OllamaDataProvider',
    'AzureDataProvider',
    'extract_azure_deployment_name',
]
