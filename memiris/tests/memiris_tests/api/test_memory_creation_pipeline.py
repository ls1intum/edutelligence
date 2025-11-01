from uuid import UUID

import pytest

from memiris.api.memory_creation_pipeline import (
    MemoryCreationPipeline,
    MemoryCreationPipelineBuilder,
    _MemoryCreationLearningDeduplicatorConfig,
    _MemoryCreationLearningExtractorConfig,
)
from memiris.domain.learning import Learning
from memiris.domain.memory import Memory
from memiris.repository.learning_repository import LearningRepository
from memiris.repository.memory_repository import MemoryRepository
from memiris.service.learning_deduplication import LearningDeduplicator
from memiris.service.learning_extraction import LearningExtractor
from memiris.service.memory_creator.memory_creator_multi_model import (
    MemoryCreatorMultiModel,
)
from memiris.service.ollama_wrapper import OllamaService
from memiris.service.vectorizer import Vectorizer


class TestMemoryCreationPipeline:
    """Test suite for MemoryCreationPipelineBuilder and MemoryCreationPipeline."""

    @pytest.fixture
    def mock_ollama_service(self, mocker):
        return mocker.Mock(spec=OllamaService)

    @pytest.fixture
    def mock_learning_repository(self, mocker):
        return mocker.Mock(spec=LearningRepository)

    @pytest.fixture
    def mock_memory_repository(self, mocker):
        return mocker.Mock(spec=MemoryRepository)

    @pytest.fixture
    def mock_vectorizer(self, mocker):
        return mocker.Mock(spec=Vectorizer)

    def test_build_adds_default_deduplicator_if_missing(
        self,
        mocker,
        mock_ollama_service,
        mock_learning_repository,
        mock_memory_repository,
        mock_vectorizer,
    ):
        # Arrange
        builder = MemoryCreationPipelineBuilder(ollama_service=mock_ollama_service)
        # Set required repositories and vectorizer
        builder.set_learning_repository(mock_learning_repository)
        builder.set_memory_repository(mock_memory_repository)
        builder.set_vectorizer(mock_vectorizer)

        # Add only a learning extractor and memory creator, but no deduplicator
        builder.add_learning_extractor(
            focus="test focus", llm_learning_extraction="test-llm"
        )
        builder.set_memory_creator_multi_model(
            llm_tool="tool-llm",
            llm_thinking="thinking-llm",
            llm_response="response-llm",
        )

        # Patch the add_learning_deduplicator method to track if it is called
        add_dedup_spy = mocker.spy(builder, "add_learning_deduplicator")

        # Act
        pipeline = builder.build()

        # Assert
        # The builder should have called add_learning_deduplicator to add a default
        assert add_dedup_spy.call_count == 1
        # The resulting pipeline should be an instance of MemoryCreationPipeline
        assert isinstance(pipeline, MemoryCreationPipeline)
        # There should be at least one deduplicator in the pipeline
        assert len(pipeline._learning_deduplicators) >= 1

    def test_build_pipeline_success(
        self,
        mock_ollama_service,
        mock_learning_repository,
        mock_memory_repository,
        mock_vectorizer,
    ):
        builder = MemoryCreationPipelineBuilder(ollama_service=mock_ollama_service)
        builder._learning_repository = mock_learning_repository
        builder._memory_repository = mock_memory_repository
        builder._vectorizer = mock_vectorizer

        builder.add_learning_extractor(focus="focus", llm_learning_extraction="llm1")
        builder.add_learning_deduplicator(llm_learning_deduplication="llm2")
        builder.set_memory_creator_multi_model(
            llm_tool="tool-llm",
            llm_thinking="thinking-llm",
            llm_response="response-llm",
        )

        pipeline = builder.build()

        assert isinstance(pipeline, MemoryCreationPipeline)
        assert len(pipeline._learning_extractors) == 1
        assert len(pipeline._learning_deduplicators) == 1
        assert isinstance(pipeline._memory_creator, MemoryCreatorMultiModel)

    def test_learning_extractor_and_deduplicator_conversion(self, mock_ollama_service):
        extractor_config = _MemoryCreationLearningExtractorConfig(
            llm_learning_extraction="llm-extract",
            focus="focus-topic",
            ollama_service=mock_ollama_service,
            template="template-path",
        )
        deduplicator_config = _MemoryCreationLearningDeduplicatorConfig(
            llm_learning_deduplication="llm-dedupe",
            ollama_service=mock_ollama_service,
            template="template-path",
        )

        extractor = extractor_config.convert()
        deduplicator = deduplicator_config.convert()

        assert isinstance(extractor, LearningExtractor)
        assert extractor.llm == "llm-extract"
        assert extractor.focus == "focus-topic"
        assert extractor.ollama_service == mock_ollama_service

        assert isinstance(deduplicator, LearningDeduplicator)
        assert deduplicator.llm == "llm-dedupe"
        assert deduplicator.ollama_service == mock_ollama_service

    def test_create_memory_pipeline_flow(
        self, mocker, mock_learning_repository, mock_memory_repository, mock_vectorizer
    ):
        # Mock LearningExtractor and LearningDeduplicator
        mock_extractor = mocker.Mock(spec=LearningExtractor)
        mock_deduplicator = mocker.Mock(spec=LearningDeduplicator)
        mock_memory_creator = mocker.Mock(spec=MemoryCreatorMultiModel)

        # Setup extractor to return a list of learnings
        fake_learnings = ["learning1", "learning2"]
        mock_extractor.extract.return_value = fake_learnings

        # Setup deduplicator to return a deduplicated list
        deduped_learnings = [
            Learning(
                uid=mocker.Mock(spec=UUID),
                title="test",
                content="test",
                reference="test",
            )
        ]
        mock_deduplicator.deduplicate.return_value = deduped_learnings

        # Setup learning repository to return the deduplicated learnings on save
        mock_learning_repository.save_all.return_value = deduped_learnings

        mock_memory_creator.create.return_value = [
            Memory(
                uid=mocker.Mock(spec=UUID),
                title="Memory Title",
                content="Memory Content",
                slept_on=False,
                deleted=False,
                learnings=[learning.id for learning in deduped_learnings],
            )
        ]

        mock_memory_repository.save_all.return_value = (
            mock_memory_creator.create.return_value
        )

        pipeline = MemoryCreationPipeline(
            learning_extractors=[mock_extractor, mock_extractor],
            learning_deduplicators=[mock_deduplicator],
            memory_creator=mock_memory_creator,
            learning_repository=mock_learning_repository,
            memory_repository=mock_memory_repository,
            vectorizer=mock_vectorizer,
        )

        tenant = "tenant1"
        content = "Some content to extract learnings from"

        pipeline.create_memories(tenant, content, reference="Test")

        mock_extractor.extract.assert_called()
        mock_deduplicator.deduplicate.assert_called_once_with(
            fake_learnings + fake_learnings
        )

    def test_build_without_learning_extractor_raises(
        self,
        mock_ollama_service,
        mock_learning_repository,
        mock_memory_repository,
        mock_vectorizer,
    ):
        builder = MemoryCreationPipelineBuilder(ollama_service=mock_ollama_service)
        builder._learning_repository = mock_learning_repository
        builder._memory_repository = mock_memory_repository
        builder._vectorizer = mock_vectorizer
        builder.set_memory_creator_multi_model(
            llm_tool="tool-llm",
            llm_thinking="thinking-llm",
            llm_response="response-llm",
        )

        with pytest.raises(
            ValueError, match="At least one LearningExtractor must be configured."
        ):
            builder.build()

    def test_build_without_memory_creator_creates_default(
        self,
        mock_ollama_service,
        mock_learning_repository,
        mock_memory_repository,
        mock_vectorizer,
    ):
        builder = MemoryCreationPipelineBuilder(ollama_service=mock_ollama_service)
        builder._learning_repository = mock_learning_repository
        builder._memory_repository = mock_memory_repository
        builder._vectorizer = mock_vectorizer
        builder.add_learning_extractor(focus="focus", llm_learning_extraction="llm1")

        pipeline = builder.build()

        assert pipeline._memory_creator is not None
