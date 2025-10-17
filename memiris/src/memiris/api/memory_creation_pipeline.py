from abc import ABC, abstractmethod
from typing import overload

try:
    # Python 3.13+
    from warnings import deprecated  # type: ignore
except ImportError:  # pragma: no cover
    from typing_extensions import deprecated
from langfuse._client.observe import observe
from weaviate.client import WeaviateClient

from memiris.domain.learning import Learning
from memiris.domain.memory import Memory
from memiris.repository.learning_repository import LearningRepository
from memiris.repository.memory_repository import MemoryRepository
from memiris.repository.weaviate.weaviate_learning_repository import (
    WeaviateLearningRepository,
)
from memiris.repository.weaviate.weaviate_memory_repository import (
    WeaviateMemoryRepository,
)
from memiris.service.learning_deduplication import LearningDeduplicator
from memiris.service.learning_extraction import LearningExtractor
from memiris.service.memory_creator.memory_creator import MemoryCreator
from memiris.service.memory_creator.memory_creator_langchain import (
    MemoryCreatorLangChain,
)
from memiris.service.memory_creator.memory_creator_multi_model import (
    MemoryCreatorMultiModel,
)
from memiris.service.ollama_wrapper import OllamaService
from memiris.service.vectorizer import Vectorizer


class _MemoryCreationLearningExtractorConfig:
    """
    Configuration class for LearningExtractor in MemoryCreationPipeline.
    This class holds the configuration for the LearningExtractor.
    """

    llm_learning_extraction: str
    focus: str
    template: str | None
    ollama_service: OllamaService

    def __init__(
        self,
        llm_learning_extraction: str,
        focus: str,
        ollama_service: OllamaService,
        template: str | None = None,
    ):
        self.llm_learning_extraction = llm_learning_extraction
        self.focus = focus
        self.ollama_service = ollama_service
        self.template = template

    def convert(self) -> LearningExtractor:
        """
        Convert the configuration to a LearningExtractor instance.
        """
        return LearningExtractor(
            llm=self.llm_learning_extraction,
            ollama_service=self.ollama_service,
            focus=self.focus,
            template=self.template,
        )


class _MemoryCreationLearningDeduplicatorConfig:
    """
    Configuration class for LearningDeduplicator in MemoryCreationPipeline.
    This class holds the configuration for the LearningDeduplicator.
    """

    llm_learning_deduplication: str
    ollama_service: OllamaService
    template: str | None

    def __init__(
        self,
        llm_learning_deduplication: str,
        ollama_service: OllamaService,
        template: str | None = None,
    ):
        self.llm_learning_deduplication = llm_learning_deduplication
        self.ollama_service = ollama_service
        self.template = template

    def convert(self) -> LearningDeduplicator:
        """
        Convert the configuration to a LearningDeduplicator instance.
        """
        return LearningDeduplicator(
            llm=self.llm_learning_deduplication,
            ollama_service=self.ollama_service,
            template=self.template,
        )


class _MemoryCreationMemoryCreatorConfig(ABC):
    """
    Abstract base configuration class for MemoryCreator in MemoryCreationPipeline.
    This class holds the configuration for the MemoryCreator.
    """

    @abstractmethod
    def convert(
        self,
        learning_repository: LearningRepository,
        memory_repository: MemoryRepository,
        vectorizer: Vectorizer,
    ) -> MemoryCreator:
        pass


class _MemoryCreationMemoryCreatorMultiModelConfig(_MemoryCreationMemoryCreatorConfig):
    """
    Configuration class for MemoryCreator in MemoryCreationPipeline.
    This class holds the configuration for the MemoryCreator.
    """

    llm_tool: str
    llm_thinking: str
    llm_response: str
    template: str | None
    ollama_service: OllamaService

    def __init__(
        self,
        llm_tool: str,
        llm_thinking: str,
        llm_response: str,
        ollama_service: OllamaService,
        template: str | None = None,
    ):
        self.llm_tool = llm_tool
        self.llm_thinking = llm_thinking
        self.llm_response = llm_response
        self.ollama_service = ollama_service
        self.template = template

    def convert(
        self,
        learning_repository: LearningRepository,
        memory_repository: MemoryRepository,
        vectorizer: Vectorizer,
    ) -> MemoryCreatorMultiModel:
        """
        Convert the configuration to a MemoryCreator instance.
        """
        return MemoryCreatorMultiModel(
            tool_llm=self.llm_tool,
            thinking_llm=self.llm_thinking,
            response_llm=self.llm_response,
            learning_repository=learning_repository,
            memory_repository=memory_repository,
            vectorizer=vectorizer,
            ollama_service=self.ollama_service,
            template=self.template,
        )


class _MemoryCreationMemoryCreatorLangchainConfig(_MemoryCreationMemoryCreatorConfig):
    """
    Configuration class for MemoryCreator in MemoryCreationPipeline using LangChain.
    This class holds the configuration for the MemoryCreator.
    """

    llm: str
    template: str | None
    ollama_service: OllamaService

    def __init__(
        self,
        llm: str,
        ollama_service: OllamaService,
        template: str | None = None,
    ):
        self.llm = llm
        self.ollama_service = ollama_service
        self.template = template

    def convert(
        self,
        learning_repository: LearningRepository,
        memory_repository: MemoryRepository,
        vectorizer: Vectorizer,
    ) -> MemoryCreator:
        """
        Convert the configuration to a MemoryCreator instance.
        """

        return MemoryCreatorLangChain(
            llm=self.ollama_service.langchain_client(self.llm),
            learning_repository=learning_repository,
            memory_repository=memory_repository,
            vectorizer=vectorizer,
            template=self.template,
        )


class MemoryCreationPipelineBuilder:
    """
    Builder class for MemoryCreationPipeline.
    This class is used to create an instance of MemoryCreationPipeline with the necessary services.
    """

    _ollama_service: OllamaService
    _llm_learning_extractor_configs: list[_MemoryCreationLearningExtractorConfig]
    _llm_learning_deduplicator_configs: list[_MemoryCreationLearningDeduplicatorConfig]
    _memory_creator_config: _MemoryCreationMemoryCreatorConfig | None
    _learning_repository: LearningRepository | None
    _memory_repository: MemoryRepository | None
    _vectorizer: Vectorizer | None

    def __init__(self, ollama_service: OllamaService):
        if not ollama_service:
            raise ValueError("OllamaService must be provided.")
        self._ollama_service = ollama_service
        self._llm_learning_extractor_configs = []
        self._llm_learning_deduplicator_configs = []
        self._memory_creator_config = None
        self._learning_repository = None
        self._memory_repository = None
        self._vectorizer = None

    def add_learning_extractor(
        self,
        focus: str,
        llm_learning_extraction: str = "gemma3:27b",
        template: str | None = None,
    ) -> "MemoryCreationPipelineBuilder":
        self._llm_learning_extractor_configs.append(
            _MemoryCreationLearningExtractorConfig(
                llm_learning_extraction=llm_learning_extraction,
                ollama_service=self._ollama_service,
                focus=focus,
                template=template,
            )
        )
        return self

    def add_learning_deduplicator(
        self,
        llm_learning_deduplication: str = "gemma3:27b",
        template: str | None = None,
    ) -> "MemoryCreationPipelineBuilder":
        self._llm_learning_deduplicator_configs.append(
            _MemoryCreationLearningDeduplicatorConfig(
                llm_learning_deduplication=llm_learning_deduplication,
                ollama_service=self._ollama_service,
                template=template,
            )
        )
        return self

    @deprecated("Use set_memory_creator_multi_model instead")
    def set_memory_creator(
        self,
        llm_tool: str = "mistral-small3.1:24b",
        llm_thinking: str = "qwen3:30b-a3b",
        llm_response: str = "gemma3:27b",
        template: str | None = None,
    ) -> "MemoryCreationPipelineBuilder":
        """
        Deprecated: Set the MemoryCreator for the pipeline using a multi-model agent approach.
        See set_memory_creator_multi_model for details.
        """
        return self.set_memory_creator_multi_model(
            llm_tool=llm_tool,
            llm_thinking=llm_thinking,
            llm_response=llm_response,
            template=template,
        )

    def set_memory_creator_multi_model(
        self,
        llm_tool: str = "mistral-small3.1:24b",
        llm_thinking: str = "qwen3:30b-a3b",
        llm_response: str = "gemma3:27b",
        template: str | None = None,
    ) -> "MemoryCreationPipelineBuilder":
        """
        Set the MemoryCreator for the pipeline using a multi-model agent approach.
        Requires three different models: one for tool operations, one for thinking,
        and one for generating the final JSON response.

        Args:
            llm_tool: An LLM with native tool-calling capabilities
            llm_thinking: An LLM optimized for reasoning and planning
            llm_response: An LLM optimized for generating JSON responses
            template: Optional Jinja2 template string. If None, use the default file.

        Returns:
            MemoryCreationPipelineBuilder: The current instance of MemoryCreationPipelineBuilder for method chaining.
        """
        self._memory_creator_config = _MemoryCreationMemoryCreatorMultiModelConfig(
            llm_tool=llm_tool,
            llm_thinking=llm_thinking,
            llm_response=llm_response,
            ollama_service=self._ollama_service,
            template=template,
        )
        return self

    def _set_memory_creator_langchain(
        self,
        llm: str = "gpt-oss:120b",
        template: str | None = None,
    ) -> "MemoryCreationPipelineBuilder":
        """
        Set the MemoryCreator for the pipeline using a single LangChain agent approach.
        Requires one model that supports tool-calling, reasoning and JSON generation.

        Args:
            llm: An LLM with native tool-calling, reasoning/planning and JSON generation capabilities
            template: Optional Jinja2 template string. If None, use the default file.

        Returns:
            MemoryCreationPipelineBuilder: The current instance of MemoryCreationPipelineBuilder for method chaining.
        """
        self._memory_creator_config = _MemoryCreationMemoryCreatorLangchainConfig(
            llm=llm,
            ollama_service=self._ollama_service,
            template=template,
        )
        return self

    @overload
    def set_learning_repository(
        self, value: LearningRepository
    ) -> "MemoryCreationPipelineBuilder":
        """
        Set the learning repository for the pipeline by providing a LearningRepository instance.

        Args:
            value: An instance of LearningRepository to handle learning operations.

        Returns:
            MemorySleepPipelineBuilder: The current instance of MemorySleepPipelineBuilder for method chaining.
        """

    @overload
    def set_learning_repository(
        self, value: WeaviateClient
    ) -> "MemoryCreationPipelineBuilder":
        """
        Set the learning repository for the pipeline by providing a WeaviateClient instance.

        Args:
            value: An instance of WeaviateClient to handle learning operations.

        Returns:
            MemorySleepPipelineBuilder: The current instance of MemorySleepPipelineBuilder for method chaining.
        """

    def set_learning_repository(
        self, value: LearningRepository | WeaviateClient
    ) -> "MemoryCreationPipelineBuilder":
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
    def set_vectorizer(self, value: Vectorizer) -> "MemoryCreationPipelineBuilder":
        """
        Set the vectorizer for the pipeline by providing a Vectorizer instance.

        Args:
            value: An instance of Vectorizer to handle embedding models.

        Returns:
            MemoryCreationPipelineBuilder: The current instance of MemoryCreationPipelineBuilder for method chaining.
        """

    @overload
    def set_vectorizer(self, value: list[str]) -> "MemoryCreationPipelineBuilder":
        """
        Set the vectorizer for the pipeline by providing a list of embedding model names.

        Args:
            value: A list of strings representing embedding model names.

        Returns:
            MemoryCreationPipelineBuilder: The current instance of MemoryCreationPipelineBuilder for method chaining.
        """

    def set_vectorizer(
        self, value: Vectorizer | list[str]
    ) -> "MemoryCreationPipelineBuilder":
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
        self, value: MemoryRepository
    ) -> "MemoryCreationPipelineBuilder":
        """
        Set the memory repository for the pipeline by providing a MemoryRepository instance.

        Args:
            value: An instance of MemoryRepository to handle memory operations.

        Returns:
            MemoryCreationPipelineBuilder: The current instance of MemoryCreationPipelineBuilder for method chaining.
        """

    @overload
    def set_memory_repository(
        self, value: WeaviateClient
    ) -> "MemoryCreationPipelineBuilder":
        """
        Set the memory repository for the pipeline by providing a WeaviateClient instance.

        Args:
            value: An instance of WeaviateClient to handle memory operations.

        Returns:
            MemoryCreationPipelineBuilder: The current instance of MemoryCreationPipelineBuilder for method chaining.
        """

    def set_memory_repository(
        self, value: MemoryRepository | WeaviateClient
    ) -> "MemoryCreationPipelineBuilder":
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

    def build(self) -> "MemoryCreationPipeline":
        if not self._llm_learning_extractor_configs:
            raise ValueError("At least one LearningExtractor must be configured.")
        if not self._learning_repository:
            raise ValueError("LearningRepository must be set.")
        if not self._memory_repository:
            raise ValueError("MemoryRepository must be set.")
        if not self._vectorizer:
            raise ValueError("Vectorizer must be set.")
        if not self._llm_learning_deduplicator_configs:
            print("No LearningDeduplicator configured, using default.")
            self.add_learning_deduplicator()
        if not self._memory_creator_config:
            print("No MemoryCreator configured, using default.")
            self._set_memory_creator_langchain()

        return MemoryCreationPipeline(
            learning_extractors=[
                config.convert() for config in self._llm_learning_extractor_configs
            ],
            learning_deduplicators=[
                config.convert() for config in self._llm_learning_deduplicator_configs
            ],
            memory_creator=self._memory_creator_config.convert(  # type: ignore
                learning_repository=self._learning_repository,
                memory_repository=self._memory_repository,
                vectorizer=self._vectorizer,
            ),
            learning_repository=self._learning_repository,
            memory_repository=self._memory_repository,
            vectorizer=self._vectorizer,
        )


class MemoryCreationPipeline:
    """
    Memory Creation Pipeline class that orchestrates the creation of memory.
    """

    _learning_extractors: list[LearningExtractor]
    _learning_deduplicators: list[LearningDeduplicator]
    _memory_creator: MemoryCreator
    _learning_repository: LearningRepository
    _memory_repository: MemoryRepository
    _vectorizer: Vectorizer

    def __init__(
        self,
        learning_extractors: list[LearningExtractor],
        learning_deduplicators: list[LearningDeduplicator],
        memory_creator: MemoryCreator,
        learning_repository: LearningRepository,
        memory_repository: MemoryRepository,
        vectorizer: Vectorizer,
    ):
        self._learning_extractors = learning_extractors
        self._learning_deduplicators = learning_deduplicators
        self._memory_creator = memory_creator
        self._learning_repository = learning_repository
        self._memory_repository = memory_repository
        self._vectorizer = vectorizer

    @observe(name="memiris.memory_creation_pipeline.create_memories")
    def create_memories(self, tenant: str, content: str, **kwargs) -> list[Memory]:
        """
        Create memories from the provided content by extracting learnings, deduplicating them,
        and creating memory entries.

        Args:
            tenant: The tenant to which the memories belong.
            content: The content from which learnings will be extracted.
            **kwargs: Additional keyword arguments that may be used by the extractors or deduplicators.

        Returns:
            list[Memory]: A list of Memory objects created from the extracted and deduplicated learnings.
        """
        learnings = []
        for extractor in self._learning_extractors:
            learnings.extend(extractor.extract(content, **kwargs))

        deduplicated_learnings: list[Learning] = []
        if len(self._learning_extractors) > 1:
            for deduplicator in self._learning_deduplicators:
                deduplicated_learnings.extend(
                    deduplicator.deduplicate(learnings, **kwargs)
                )

        for learning in deduplicated_learnings:
            learning.vectors = self._vectorizer.vectorize(learning.content)

        saved_learnings = self._learning_repository.save_all(
            tenant=tenant, entities=deduplicated_learnings
        )

        memories = self._memory_creator.create(
            learnings=saved_learnings, tenant=tenant, **kwargs
        )

        for memory in memories:
            memory.vectors = self._vectorizer.vectorize(memory.content)

        saved_memories = self._memory_repository.save_all(
            tenant=tenant, entities=memories
        )

        return saved_memories
