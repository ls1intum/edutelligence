import uuid
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
from memiris.repository.weaviate.weaviate_memory_connection_repository import (
    WeaviateMemoryConnectionRepository,
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
        mock_vectorizer.vectorize.return_value = {"vector_0": mock_vector()}
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
    def memory_connection_repository(self, weaviate_client):
        """Create a real memory connection repository backed by Weaviate."""
        return WeaviateMemoryConnectionRepository(weaviate_client)

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
        memory_connection_repository,
        mock_vectorizer,
    ):
        """Create a MemorySleeper instance for testing."""
        return MemorySleeper(
            tool_llm="test-tool-model",
            response_llm="test-response-model",
            learning_repository=learning_repository,
            memory_repository=memory_repository,
            memory_connection_repository=memory_connection_repository,
            vectorizer=mock_vectorizer,
            ollama_service=mock_ollama_service,
            template_deduplication="",
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

    def test_deduplicate_with_existing_memories_empty_list(
        self, memory_sleeper, tenant
    ):
        """Test _deduplicate_with_existing_memories with an empty memory list."""
        result = memory_sleeper._deduplicate_with_existing_memories([], tenant)
        assert result == []

    def test_deduplicate_with_existing_memories_no_vectors(
        self, memory_sleeper, tenant
    ):
        """Test _deduplicate_with_existing_memories when memories don't have vectors."""
        memories = [
            Memory(
                uid=uuid.uuid4(),
                title="Memory without vectors",
                content="Content",
                learnings=[],
            )
        ]
        result = memory_sleeper._deduplicate_with_existing_memories(memories, tenant)
        assert result == memories

    def test_deduplicate_with_existing_memories_functionality(
        self,
        memory_sleeper,
        tenant,
        sample_memories,
    ):
        """Test functionality of _deduplicate_with_existing_memories without mocking threading."""
        # Mock memory_repository's search_multi method
        memory_sleeper.memory_repository.search_multi = MagicMock(
            return_value=[sample_memories[2]]
        )

        # Create a mock for the process_chunk method that will use _deduplicate_memories
        original_process_chunk = memory_sleeper._process_chunk
        memory_sleeper._process_chunk = MagicMock(
            return_value=[sample_memories[0], sample_memories[2]]
        )

        try:
            # Call the method with only memories that have vectors
            memories_with_vectors = [m for m in sample_memories if m.vectors]
            result = memory_sleeper._deduplicate_with_existing_memories(
                memories_with_vectors, tenant
            )

            # Verify _process_chunk was called
            assert memory_sleeper._process_chunk.called
            assert len(result) > 0
        finally:
            # Restore the original method
            memory_sleeper._process_chunk = original_process_chunk

    def test_process_chunk_without_similar_memories(
        self,
        memory_sleeper,
        tenant,
        sample_memories,
    ):
        """Test _process_chunk when no similar memories are found."""
        # Mock memory_repository's search_multi to return empty list
        memory_sleeper.memory_repository.search_multi = MagicMock(return_value=[])

        # Store the original method to restore later
        original_deduplicate_memories = memory_sleeper._deduplicate_memories
        # Replace with a mock to check if it's called
        memory_sleeper._deduplicate_memories = MagicMock(return_value=[])

        try:
            # Call the method with a chunk of memories
            chunk = [sample_memories[0]]
            result = memory_sleeper._process_chunk(chunk, tenant)

            # Verify result and that search_multi was called
            assert result == chunk
            memory_sleeper.memory_repository.search_multi.assert_called()
            # _deduplicate_memories should not be called since no similar memories found
            assert not memory_sleeper._deduplicate_memories.called
        finally:
            # Restore the original method
            memory_sleeper._deduplicate_memories = original_deduplicate_memories

    def test_process_chunk_with_similar_memories(
        self,
        memory_sleeper,
        tenant,
        sample_memories,
    ):
        """Test _process_chunk when similar memories are found."""
        # Mock memory_repository's search_multi to return a memory
        memory_sleeper.memory_repository.search_multi = MagicMock(
            return_value=[sample_memories[2]]
        )

        # Create a mock for _deduplicate_memories
        memory_sleeper._deduplicate_memories = MagicMock(
            return_value=[sample_memories[0], sample_memories[2]]
        )

        # Call the method with a chunk of memories
        chunk = [sample_memories[0]]
        memory_sleeper._process_chunk(chunk, tenant)

        # Verify _deduplicate_memories was called with combined memories
        memory_sleeper._deduplicate_memories.assert_called_once()
        call_args = memory_sleeper._deduplicate_memories.call_args[0]
        assert len(call_args[0]) == 2  # Combined memories (chunk + similar)
        assert call_args[1] == tenant  # Tenant

    def test_deduplicate_with_existing_memories_integration(
        self,
        memory_sleeper,
        tenant,
        sample_memories,
        mock_ollama_service,
    ):
        """Integration test for _deduplicate_with_existing_memories with real method calls."""
        # Create a new memory similar to existing ones
        new_memory = Memory(
            uid=None,
            title="New Python Memory",
            content="The user is learning about Python programming concepts.",
            learnings=[],
            vectors={"vector_0": mock_vector()},
        )

        # Save the new memory
        new_memory = memory_sleeper.memory_repository.save(tenant, new_memory)

        # Mock memory_repository's search_multi to return our sample memory
        memory_sleeper.memory_repository.search_multi = MagicMock(
            return_value=[sample_memories[0]]
        )

        # Mock response from LLM for deduplicate_memories
        deduplicated_dto = [
            MemoryDeduplicationDto(
                title="Combined Python Memory",
                content="The user is interested in learning Python programming language.",
                memories=[new_memory.id, sample_memories[0].id],
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

        # Call the method with our new memory
        result = memory_sleeper._deduplicate_with_existing_memories(
            [new_memory], tenant
        )

        # Verify that search_multi was called for vector similarity search
        memory_sleeper.memory_repository.search_multi.assert_called()

        # Verify that a combined memory was created
        combined_memory = next(
            (m for m in result if m.title == "Combined Python Memory"), None
        )
        assert combined_memory is not None

    def test_run_sleep_with_existing_memories(
        self,
        memory_sleeper,
        tenant,
        sample_memories,
    ):
        """Test the run_sleep method with deduplication against existing memories."""
        # Mock the memory repository to return our sample memories
        memory_sleeper.memory_repository.find_unslept_memories = MagicMock(
            return_value=sample_memories[:2]  # Return first two memories
        )

        # Mock the deduplicate methods
        original_deduplicate = memory_sleeper._deduplicate_memories
        memory_sleeper._deduplicate_memories = MagicMock(
            return_value=sample_memories[:2]
        )

        original_deduplicate_with_existing = (
            memory_sleeper._deduplicate_with_existing_memories
        )
        memory_sleeper._deduplicate_with_existing_memories = MagicMock(
            return_value=[sample_memories[0]]
        )

        # Save original run_sleep to restore later
        original_method = memory_sleeper.run_sleep

        # Call the method - no need to patch since deduplicate_with_existing_memories is already activated
        # in the code now
        try:
            # Call the method
            memory_sleeper.run_sleep(tenant)

            # Verify that both deduplication methods were called
            memory_sleeper._deduplicate_memories.assert_called_once()
            memory_sleeper._deduplicate_with_existing_memories.assert_called_once()

        finally:
            # Restore original methods
            memory_sleeper._deduplicate_memories = original_deduplicate
            memory_sleeper._deduplicate_with_existing_memories = (
                original_deduplicate_with_existing
            )
            memory_sleeper.run_sleep = original_method

    def test_deduplicate_with_existing_memories_calls_method_per_chunk(
        self,
        memory_sleeper,
        tenant,
    ):
        """Test that _deduplicate_memories is called once for each memory chunk."""
        # Create many memories to ensure we get multiple chunks
        num_memories = 15  # With chunk size 5, this should create 3 chunks
        memories = []
        for i in range(num_memories):
            memory = Memory(
                uid=f"test-id-{i}",
                title=f"Memory {i}",
                content=f"Content {i}",
                learnings=[],
                vectors={"vector_0": mock_vector()},
            )
            memories.append(memory)

        # Mock the search_multi method to return some results
        memory_sleeper.memory_repository.search_multi = MagicMock(
            return_value=[memories[0]]
        )

        # Mock the _deduplicate_memories method
        memory_sleeper._deduplicate_memories = MagicMock(
            side_effect=lambda memories, *args, **kwargs: memories
        )

        # Override the _process_chunk method to track actual calls to _deduplicate_memories
        original_process_chunk = memory_sleeper._process_chunk
        memory_sleeper._process_chunk = MagicMock(side_effect=original_process_chunk)

        # Call the method
        memory_sleeper._deduplicate_with_existing_memories(memories, tenant)

        # Verify that _process_chunk was called for each chunk (should be 3)
        assert memory_sleeper._process_chunk.call_count == 3

        # Get the call args for all three calls
        call_args_list = memory_sleeper._process_chunk.call_args_list

        # We know the total number should be 15 memories
        total_memories = 0
        for call_args in call_args_list:
            chunk = call_args[0][0]  # First arg, first param is the chunk
            # Each chunk should have at least 1 memory but no more than 5
            assert len(chunk) > 0
            assert len(chunk) <= 5
            total_memories += len(chunk)

        # Verify that all memories were processed
        assert total_memories == num_memories
