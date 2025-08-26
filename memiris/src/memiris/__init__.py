"""
MemIris: A Python package for long-term memory management in large language models.
"""

from importlib.metadata import PackageNotFoundError, version  # pragma: no cover

from memiris.api.learning_service import LearningService
from memiris.api.memory_connection_service import MemoryConnectionService
from memiris.api.memory_creation_pipeline import (
    MemoryCreationPipeline,
    MemoryCreationPipelineBuilder,
)
from memiris.api.memory_dto import MemoryDTO
from memiris.api.memory_service import MemoryService
from memiris.api.memory_sleep_pipeline import (
    MemorySleepPipeline,
    MemorySleepPipelineBuilder,
)
from memiris.domain.learning import Learning
from memiris.domain.memory import Memory
from memiris.domain.memory_connection import MemoryConnection
from memiris.service.ollama_wrapper import OllamaService

try:
    dist_name = "MemIris"
    __version__ = version(dist_name)
except PackageNotFoundError:  # pragma: no cover
    __version__ = "unknown"
finally:
    del version, PackageNotFoundError

__all__ = [
    # Domain Models
    "Memory",
    "MemoryDTO",
    "Learning",
    "MemoryConnection",
    # API services
    "MemorySleepPipeline",
    "MemorySleepPipelineBuilder",
    "MemoryCreationPipeline",
    "MemoryCreationPipelineBuilder",
    "MemoryService",
    "MemoryConnectionService",
    "LearningService",
    # Internal services
    "OllamaService",
]
