from typing import overload

from langfuse._client.observe import observe
from weaviate.client import WeaviateClient

from memiris.repository.learning_repository import LearningRepository
from memiris.repository.memory_connection_repository import MemoryConnectionRepository
from memiris.repository.memory_repository import MemoryRepository
from memiris.repository.weaviate.weaviate_learning_repository import (
    WeaviateLearningRepository,
)
from memiris.repository.weaviate.weaviate_memory_connection_repository import (
    WeaviateMemoryConnectionRepository,
)
from memiris.repository.weaviate.weaviate_memory_repository import (
    WeaviateMemoryRepository,
)
from memiris.service.memory_sleep import MemorySleeper
from memiris.service.ollama_wrapper import OllamaService
from memiris.service.vectorizer import Vectorizer


class MemorySleepPipelineBuilder:
    """
    Builder class for MemorySleepPipeline.
    This class is used to create an instance of MemorySleepPipeline with the necessary services.
    """

    _tool_llm: str
    _response_llm: str
    _learning_repository: LearningRepository | None
    _memory_repository: MemoryRepository | None
    _memory_connection_repository: MemoryConnectionRepository | None
    _vectorizer: Vectorizer | None
    _ollama_service: OllamaService

    _template_deduplication: str | None
    _template_connector: str | None

    _max_threads: int | None  # Maximum number of threads for parallel processing
    _group_size: (
        int | None
    )  # Size of memory groups, can be larger to meet the max_groups limit
    _max_groups: int | None  # Maximum number of groups to process in parallel

    def __init__(self, ollama_service: OllamaService):
        if not ollama_service:
            raise ValueError("OllamaService must be provided.")
        self._ollama_service = ollama_service
        self._tool_llm = "mistral-small3.1:24b"
        self._response_llm = "gemma3:27b"
        self._learning_repository = None
        self._memory_repository = None
        self._memory_connection_repository = None
        self._vectorizer = None
        self._template_deduplication = None
        self._template_connector = None
        self._max_threads = None
        self._group_size = None
        self._max_groups = None

    def set_tool_llm(self, tool_llm: str | None) -> "MemorySleepPipelineBuilder":
        """
        Set the tool language model.
        """
        if not tool_llm:
            self._tool_llm = "mistral-small3.1:24b"
        else:
            self._tool_llm = tool_llm
        return self

    def set_response_llm(
        self, response_llm: str | None
    ) -> "MemorySleepPipelineBuilder":
        """
        Set the response language model.
        """
        if not response_llm:
            self._response_llm = "gemma3:27b"
        else:
            self._response_llm = response_llm
        return self

    def set_deduplication_template(
        self, template_deduplication: str | None
    ) -> "MemorySleepPipelineBuilder":
        """
        Set the template for deduplicating memories.
        """
        self._template_deduplication = template_deduplication
        return self

    def set_connection_template(
        self, template_connector: str | None
    ) -> "MemorySleepPipelineBuilder":
        """
        Set the template for connecting memories.
        """
        self._template_connector = template_connector
        return self

    def set_max_threads(self, max_threads: int | None) -> "MemorySleepPipelineBuilder":
        """
        Set the maximum number of threads for parallel processing.
        """
        if max_threads is not None and max_threads <= 0:
            raise ValueError("max_threads must be a positive integer.")
        self._max_threads = max_threads
        return self

    def set_group_size(self, group_size: int | None) -> "MemorySleepPipelineBuilder":
        """
        Set the size of memory groups.
        """
        if group_size is not None and group_size <= 0:
            raise ValueError("group_size must be a positive integer.")
        self._group_size = group_size
        return self

    @overload
    def set_learning_repository(
        self, learning_repository: LearningRepository
    ) -> "MemorySleepPipelineBuilder":
        pass

    @overload
    def set_learning_repository(
        self, weaviate_client: WeaviateClient
    ) -> "MemorySleepPipelineBuilder":
        pass

    def set_learning_repository(
        self, value: LearningRepository | WeaviateClient
    ) -> "MemorySleepPipelineBuilder":
        if not value:
            raise ValueError(
                "Either LearningRepository or WeaviateClient must be provided."
            )

        if isinstance(value, WeaviateClient):
            self._learning_repository = WeaviateLearningRepository(value)
        elif isinstance(value, LearningRepository):
            self._learning_repository = value
        else:
            raise TypeError(
                "Value must be either LearningRepository or WeaviateClient."
            )

        return self

    @overload
    def set_memory_connection_repository(
        self, memory_connection_repository: MemoryRepository
    ) -> "MemorySleepPipelineBuilder":
        pass

    @overload
    def set_memory_connection_repository(
        self, weaviate_client: WeaviateClient
    ) -> "MemorySleepPipelineBuilder":
        pass

    def set_memory_connection_repository(
        self, value: MemoryConnectionRepository | WeaviateClient
    ) -> "MemorySleepPipelineBuilder":
        if not value:
            raise ValueError(
                "Either MemoryConnectionRepository or WeaviateClient must be provided."
            )

        if isinstance(value, WeaviateClient):
            self._memory_connection_repository = WeaviateMemoryConnectionRepository(
                value
            )
        elif isinstance(value, MemoryConnectionRepository):
            self._memory_connection_repository = value
        else:
            raise TypeError(
                "Value must be either MemoryConnectionRepository or WeaviateClient."
            )

        return self

    @overload
    def set_vectorizer(self, vectorizer: Vectorizer) -> "MemorySleepPipelineBuilder":
        pass

    @overload
    def set_vectorizer(
        self, embedding_models: list[str]
    ) -> "MemorySleepPipelineBuilder":
        pass

    def set_vectorizer(
        self, value: Vectorizer | list[str]
    ) -> "MemorySleepPipelineBuilder":
        if not value:
            raise ValueError("Either Vectorizer or embedding models must be provided.")

        if isinstance(value, Vectorizer):
            self._vectorizer = value
        elif isinstance(value, list):
            self._vectorizer = Vectorizer(
                vector_models=value, ollama_service=self._ollama_service
            )
        else:
            raise TypeError(
                "Value must be either Vectorizer or a list of embedding model names."
            )

        return self

    @overload
    def set_memory_repository(
        self, memory_repository: MemoryRepository
    ) -> "MemorySleepPipelineBuilder":
        pass

    @overload
    def set_memory_repository(
        self, weaviate_client: WeaviateClient
    ) -> "MemorySleepPipelineBuilder":
        pass

    def set_memory_repository(
        self, value: MemoryRepository | WeaviateClient
    ) -> "MemorySleepPipelineBuilder":
        if not value:
            raise ValueError(
                "Either MemoryRepository or WeaviateClient must be provided."
            )

        if isinstance(value, WeaviateClient):
            self._memory_repository = WeaviateMemoryRepository(value)
        elif isinstance(value, MemoryRepository):
            self._memory_repository = value
        else:
            raise TypeError("Value must be either MemoryRepository or WeaviateClient.")

        return self

    def build(self) -> "MemorySleepPipeline":
        if not self._learning_repository:
            raise ValueError("LearningRepository must be set.")
        if not self._memory_repository:
            raise ValueError("MemoryRepository must be set.")
        if not self._memory_connection_repository:
            raise ValueError("MemoryConnectionRepository must be set.")
        if not self._vectorizer:
            raise ValueError("Vectorizer must be set.")

        return MemorySleepPipeline(
            memory_sleeper=MemorySleeper(
                tool_llm=self._tool_llm,
                response_llm=self._response_llm,
                learning_repository=self._learning_repository,
                memory_repository=self._memory_repository,
                memory_connection_repository=self._memory_connection_repository,
                vectorizer=self._vectorizer,
                ollama_service=self._ollama_service,
                template_deduplication=self._template_deduplication,
                template_connector=self._template_connector,
                max_threads=self._max_threads,
                group_size=self._group_size,
                max_groups=self._max_groups,
            )
        )


class MemorySleepPipeline:
    """
    Memory Sleep Pipeline class that handles the sleep on memories.
    """

    _memory_sleeper: MemorySleeper

    def __init__(self, memory_sleeper: MemorySleeper):
        self._memory_sleeper = memory_sleeper

    @observe(name="memiris.memory_sleep_pipeline.sleep")
    def sleep(self, tenant: str, **kwargs):
        """
        Sleep on memories using the configured MemorySleeper.
        """
        if not self._memory_sleeper:
            raise ValueError("MemorySleeper must be set.")

        return self._memory_sleeper.run_sleep(tenant, **kwargs)
