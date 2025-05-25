from unittest.mock import MagicMock

import pytest
from memiris_tests.test_utils import mock_vector
from memiris_tests.weaviate_tests.test_setup import WeaviateTest

from memiris.domain.learning import Learning
from memiris.domain.memory import Memory
from memiris.dto.memory_deduplication_dto import MemoryDeduplicationDto
from memiris.repository.weaviate.weaviate_learning_repository import (
    WeaviateLearningRepository,
)
from memiris.repository.weaviate.weaviate_memory_repository import (
    WeaviateMemoryRepository,
)
from memiris.service.memory_sleep import MemorySleeper
from memiris.service.ollama_wrapper import OllamaService, WrappedChatResponse
from memiris.service.vectorizer import Vectorizer


class TestMemorySleeper(WeaviateTest):
    """Test suite for the MemorySleeper class, focusing on memory deduplication functionality."""

    @pytest.fixture
    def mock_ollama_service(self):
        """Create a mock OllamaService."""
        mock_service = MagicMock(spec=OllamaService)
        return mock_service

    @pytest.fixture
    def mock_vectorizer(self):
        """Create a mock Vectorizer."""
        mock_vectorizer = MagicMock(spec=Vectorizer)
        mock_vectorizer.vectorize.return_value = mock_vector()
        return mock_vectorizer

    @pytest.fixture
    def mock_template(self):
        """Create a mock template."""
        mock = MagicMock()
        mock.render.return_value = "Rendered template content"
        return mock

    @pytest.fixture
    def learning_repository(self, weaviate_client):
        """Create a real learning repository backed by Weaviate."""
        return WeaviateLearningRepository(weaviate_client)

    @pytest.fixture
    def memory_repository(self, weaviate_client):
        """Create a real memory repository backed by Weaviate."""
        return WeaviateMemoryRepository(weaviate_client)

    @pytest.fixture
    def tenant(self):
        """Fixture for tenant name."""
        return "test-tenant"

    @pytest.fixture
    def sample_learnings(self, learning_repository, tenant):
        """Create a list of sample learnings for testing."""
        memories = [
            Learning(
                uid=None,
                title="Learning 1",
                content="The user is interested in Python programming.",
                reference="Test Reference",
            ),
            Learning(
                uid=None,
                title="Learning 2",
                content="The user wants to learn about Python.",
                reference="Test Reference",
            ),
            Learning(
                uid=None,
                title="Learning 3",
                content="The user is interested in JavaScript.",
                reference="Test Reference",
            ),
        ]

        return [learning_repository.save(tenant, memory) for memory in memories]

    @pytest.fixture
    def sample_memories(self, memory_repository, tenant, sample_learnings):
        """Create sample memories for testing."""
        memory1 = Memory(
            uid=None,
            title="Memory about Python",
            content="The user expressed interest in learning Python programming.",
            learnings=[sample_learnings[0].id],
            vectors={"vector_0": mock_vector()},
        )
        memory2 = Memory(
            uid=None,
            title="Python programming interest",
            content="The user wants to start learning Python programming language.",
            learnings=[sample_learnings[1].id],
            vectors={"vector_0": mock_vector()},
        )
        memory3 = Memory(
            uid=None,
            title="Database interest",
            content="The user is interested in learning about database technologies.",
            learnings=[sample_learnings[2].id],
            vectors={"vector_0": mock_vector()},
        )

        saved_memories = [
            memory_repository.save(tenant, memory1),
            memory_repository.save(tenant, memory2),
            memory_repository.save(tenant, memory3),
        ]

        return saved_memories

    @pytest.fixture
    def memory_sleeper(
        self,
        mock_ollama_service,
        learning_repository,
        memory_repository,
        mock_vectorizer,
    ):
        """Create a MemorySleeper instance for testing."""
        return MemorySleeper(
            tool_llm="test-tool-model",
            response_llm="test-response-model",
            learning_repository=learning_repository,
            memory_repository=memory_repository,
            vectorizer=mock_vectorizer,
            ollama_service=mock_ollama_service,
            template_deduplication="",
            template_deduplication_with_tools="",
            template_connector="",
        )

    def test_deduplicate_memories_empty_list(self, memory_sleeper, tenant):
        """Test deduplication with an empty memory list."""
        result = memory_sleeper._deduplicate_memories([], tenant)
        assert result == []
        memory_sleeper.ollama_service.chat.assert_not_called()

    def test_deduplicate_memories_single_memory(
        self, memory_sleeper, tenant, sample_memories
    ):
        """Test deduplication with a single memory."""
        result = memory_sleeper._deduplicate_memories([sample_memories[0]], tenant)
        assert result == [sample_memories[0]]
        memory_sleeper.ollama_service.chat.assert_not_called()

    def test_deduplicate_memories_no_valid_ids(self, memory_sleeper, tenant):
        """Test deduplication when memories don't have valid IDs."""
        memories = [Memory(title="Memory without ID", content="Content", learnings=[])]
        result = memory_sleeper._deduplicate_memories(memories, tenant)
        assert result == memories
        memory_sleeper.ollama_service.chat.assert_not_called()

    def test_deduplicate_memories_success(
        self,
        memory_sleeper,
        mock_ollama_service,
        tenant,
        sample_memories,
    ):
        """Test successful deduplication of memories."""
        # Create mock deduplicated response
        memory_id1 = sample_memories[0].id
        memory_id2 = sample_memories[1].id

        # Mock response from LLM
        deduplicated_dto = [
            MemoryDeduplicationDto(
                title="Combined Python Memory",
                content="The user is interested in learning Python programming language.",
                memories=[memory_id1, memory_id2],
            ),
        ]

        # Configure mock LLM response
        mock_message = MagicMock()
        mock_message.content = MemoryDeduplicationDto.json_array_type().dump_json(
            deduplicated_dto
        )
        mock_response = MagicMock(spec=WrappedChatResponse)
        mock_response.message = mock_message
        mock_ollama_service.chat.return_value = mock_response

        # Call the method
        result = memory_sleeper._deduplicate_memories(sample_memories, tenant)

        assert len(result) == 2

        # Find the combined memory in the results
        combined_memory = None
        for memory in result:
            if memory.title == "Combined Python Memory":
                combined_memory = memory
                break

        # Verify the combined memory was created correctly
        assert combined_memory is not None
        assert (
            combined_memory.content
            == "The user is interested in learning Python programming language."
        )
        assert combined_memory.slept_on is True

        # Check that all learnings from memory1 and memory2 are in the combined memory
        for learning_id in sample_memories[0].learnings + sample_memories[1].learnings:
            assert learning_id in combined_memory.learnings

        # Check that a memory with the Database title is in the result set
        database_memory = next(
            (m for m in result if m.title == "Database interest"), None
        )
        assert database_memory is not None
        assert database_memory.id == sample_memories[2].id

    def test_deduplicate_memories_no_duplicates_found(
        self,
        memory_sleeper,
        mock_ollama_service,
        tenant,
        sample_memories,
    ):
        """Test deduplication when no duplicates are found."""
        # Mock response from LLM - each memory is unique
        memory_dtos = []

        # Configure mock LLM response
        mock_message = MagicMock()
        mock_message.content = MemoryDeduplicationDto.json_array_type().dump_json(
            memory_dtos
        )
        mock_response = MagicMock(spec=WrappedChatResponse)
        mock_response.message = mock_message
        mock_ollama_service.chat.return_value = mock_response

        # Call the method
        result = memory_sleeper._deduplicate_memories(sample_memories, tenant)

        # Each original memory should be in the results with slept_on=True
        # Check that all original memories are in the result set
        for original_memory in sample_memories:
            found_memory = next((m for m in result if m.id == original_memory.id), None)
            assert found_memory is not None
            assert found_memory.slept_on is True

    def test_deduplicate_memories_error_response(
        self,
        memory_sleeper,
        mock_ollama_service,
        tenant,
        sample_memories,
    ):
        """Test deduplication with error in response parsing."""
        # Mock an invalid JSON response
        mock_message = MagicMock()
        mock_message.content = "invalid json"
        mock_response = MagicMock(spec=WrappedChatResponse)
        mock_response.message = mock_message
        mock_ollama_service.chat.return_value = mock_response

        # Call the method
        result = memory_sleeper._deduplicate_memories(sample_memories, tenant)

        # Should return original memories on error
        assert result == sample_memories

        # Check that none of the memories were deleted
        memory_repository = memory_sleeper.memory_repository
        for memory in sample_memories:
            retrieved_memory = memory_repository.find(tenant, memory.id)
            assert retrieved_memory.deleted is False

    def test_deduplicate_memories_no_response(
        self,
        memory_sleeper,
        mock_ollama_service,
        tenant,
        sample_memories,
    ):
        """Test deduplication with no response from ollama service."""
        # Configure mock to return None
        mock_ollama_service.chat.return_value = None

        # Call the method
        result = memory_sleeper._deduplicate_memories(sample_memories, tenant)

        # Should return original memories on error
        assert result == sample_memories

        # Check that none of the memories were deleted
        memory_repository = memory_sleeper.memory_repository
        for memory in sample_memories:
            retrieved_memory = memory_repository.find(tenant, memory.id)
            assert retrieved_memory.deleted is False
