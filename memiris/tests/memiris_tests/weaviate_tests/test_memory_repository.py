import pytest
from memiris_tests.test_utils import compare_vectors, mock_vector
from memiris_tests.weaviate_tests.test_setup import WeaviateTest
from weaviate.client import WeaviateClient

from memiris.domain.learning import Learning
from memiris.domain.memory import Memory
from memiris.repository.weaviate.weaviate_learning_repository import (
    WeaviateLearningRepository,
)
from memiris.repository.weaviate.weaviate_memory_repository import (
    WeaviateMemoryRepository,
)


class TestWeaviateMemoryRepository(WeaviateTest):
    """
    TestWeaviateMemoryRepository is a test class for WeaviateMemoryRepository.
    It uses testcontainers to run a Weaviate instance in a Docker container.
    """

    @pytest.fixture
    def learning_repository(self, weaviate_client):
        return WeaviateLearningRepository(weaviate_client)

    @pytest.fixture
    def memory_repository(self, weaviate_client):
        return WeaviateMemoryRepository(weaviate_client)

    def _create_test_learning(self, learning_repository) -> Learning:
        """Helper method to create a test learning object."""
        vec = mock_vector()
        learning = learning_repository.save(
            "test",
            Learning(
                title="Test Learning Title",
                content="Test Learning Content",
                reference="Test Learning Reference",
                vectors={"vector_0": vec},
            ),
        )
        return learning

    def _create_test_memory(self, memory_repository, learning_repository) -> Memory:
        """Helper method to create a test memory object linked to a learning."""
        vec = mock_vector()
        return memory_repository.save(
            "test",
            Memory(
                title="Test Memory Title",
                content="Test Memory Content",
                learnings=[self._create_test_learning(learning_repository).id],
                vectors={"vector_0": vec},
            ),
        )

    def test_create(self, memory_repository, learning_repository):
        """Test creating a memory with a linked learning."""
        learning = self._create_test_learning(learning_repository)
        vec = mock_vector()
        memory = memory_repository.save(
            "test",
            Memory(
                title="Test Memory Title",
                content="Test Memory Content",
                learnings=[learning.id],
                vectors={"vector_0": vec},
            ),
        )

        assert memory is not None
        assert memory.id is not None

    def test_delete(self, memory_repository, learning_repository):
        """Test deleting a memory."""
        memory = self._create_test_memory(memory_repository, learning_repository)

        memory_repository.delete("test", memory.id)

        assert memory_repository.find("test", memory.id) is None

    def test_get(self, memory_repository, learning_repository):
        """Test retrieving a memory."""
        memory = self._create_test_memory(memory_repository, learning_repository)

        retrieved_memory = memory_repository.find("test", memory.id)

        assert retrieved_memory is not None
        assert retrieved_memory.id == memory.id
        assert retrieved_memory.title == memory.title
        assert retrieved_memory.content == memory.content
        assert len(retrieved_memory.learnings) == 1
        assert retrieved_memory.learnings[0] == memory.learnings[0]

        compare_vectors(memory.vectors, retrieved_memory.vectors)

    def test_update(self, memory_repository, learning_repository):
        """Test updating a memory."""
        memory = self._create_test_memory(memory_repository, learning_repository)

        # Create another learning to add to the memory
        additional_learning = self._create_test_learning(learning_repository)

        memory.title = "Updated Memory Title"
        memory.content = "Updated Memory Content"
        memory.learnings.append(additional_learning.id)
        memory.vectors["vector_0"] = mock_vector()

        memory_repository.save("test", memory)

        updated_memory = memory_repository.find("test", memory.id)

        assert updated_memory is not None
        assert updated_memory.id == memory.id
        assert updated_memory.title == "Updated Memory Title"
        assert updated_memory.content == "Updated Memory Content"
        assert len(updated_memory.learnings) == 2
        learning_ids = updated_memory.learnings
        assert memory.learnings[0] in learning_ids
        assert additional_learning.id in learning_ids
        compare_vectors(memory.vectors, updated_memory.vectors)

    def test_all(self, memory_repository, learning_repository):
        """Test retrieving all memories."""
        memory1 = self._create_test_memory(memory_repository, learning_repository)
        memory2 = self._create_test_memory(memory_repository, learning_repository)
        memory3 = self._create_test_memory(memory_repository, learning_repository)

        all_memories = memory_repository.all("test")

        assert all_memories is not None
        assert len(all_memories) >= 3

        all_ids = [memory.id for memory in all_memories]

        assert memory1.id in all_ids
        assert memory2.id in all_ids
        assert memory3.id in all_ids

    def test_search(self, memory_repository, learning_repository):
        """Test searching for memories by vector."""
        memory1 = self._create_test_memory(memory_repository, learning_repository)
        memory2 = self._create_test_memory(memory_repository, learning_repository)
        _ = self._create_test_memory(memory_repository, learning_repository)

        search_results = memory_repository.search(
            "test", "vector_0", memory1.vectors["vector_0"], 1
        )
        assert search_results is not None
        assert len(search_results) >= 1
        assert search_results[0].id == memory1.id

        search_results = memory_repository.search(
            "test", "vector_0", memory2.vectors["vector_0"], 1
        )
        assert search_results is not None
        assert len(search_results) >= 1
        assert search_results[0].id == memory2.id

    def test_search_empty(self, weaviate_client: WeaviateClient, memory_repository):
        """Test searching for memories in an empty tenant."""
        weaviate_client.collections.get("Memory").tenants.create("test_empty")
        search_results = memory_repository.search(
            "test_empty", "vector_0", mock_vector(), 1
        )
        assert search_results is not None
        assert len(search_results) == 0

    def test_search_multi(self, memory_repository, learning_repository):
        """Test searching for memories using multiple vectors."""
        memory1 = self._create_test_memory(memory_repository, learning_repository)
        memory2 = self._create_test_memory(memory_repository, learning_repository)
        _ = self._create_test_memory(memory_repository, learning_repository)

        search_results = memory_repository.search_multi(
            "test", {"vector_0": memory1.vectors["vector_0"]}, 1
        )
        assert search_results is not None
        assert len(search_results) >= 1
        assert search_results[0].id == memory1.id

        search_results = memory_repository.search_multi(
            "test", {"vector_0": memory2.vectors["vector_0"]}, 1
        )
        assert search_results is not None
        assert len(search_results) >= 1
        assert search_results[0].id == memory2.id

    def test_search_multi_empty(
        self, weaviate_client: WeaviateClient, memory_repository
    ):
        """Test searching for memories with multiple vectors in an empty tenant."""
        weaviate_client.collections.get("Memory").tenants.create("test_empty")
        search_results = memory_repository.search_multi(
            "test_empty", {"vector_0": mock_vector()}, 1
        )
        assert search_results is not None
        assert len(search_results) == 0

    # Additional tests for the relationship between memories and learnings

    def test_memory_with_multiple_learnings(
        self, memory_repository, learning_repository
    ):
        """Test creating a memory with multiple linked learnings."""
        learning1 = self._create_test_learning(learning_repository)
        learning2 = self._create_test_learning(learning_repository)
        learning3 = self._create_test_learning(learning_repository)

        vec = mock_vector()
        memory = memory_repository.save(
            "test",
            Memory(
                title="Memory with Multiple Learnings",
                content="This memory links to three different learnings",
                learnings=[learning1.id, learning2.id, learning3.id],
                vectors={"vector_0": vec},
            ),
        )

        retrieved_memory = memory_repository.find("test", memory.id)

        assert retrieved_memory is not None
        assert len(retrieved_memory.learnings) == 3

        learning_ids = retrieved_memory.learnings
        assert learning1.id in learning_ids
        assert learning2.id in learning_ids
        assert learning3.id in learning_ids

        retrieved_learning = learning_repository.find("test", learning1.id)
        assert retrieved_learning is not None
        assert len(retrieved_learning.memories) == 1
        assert retrieved_learning.memories[0] == memory.id

    def test_update_memory_learnings(self, memory_repository, learning_repository):
        """Test updating the learnings of a memory."""
        learning1 = self._create_test_learning(learning_repository)

        # Create a memory with one learning
        memory = memory_repository.save(
            "test",
            Memory(
                title="Initial Memory",
                content="Initial content with one learning",
                learnings=[learning1.id],
                vectors={"vector_0": mock_vector()},
            ),
        )

        # Create two more learnings
        learning2 = self._create_test_learning(learning_repository)
        learning3 = self._create_test_learning(learning_repository)

        # Update to replace the learning with two new ones
        memory.learnings = [learning2.id, learning3.id]
        memory_repository.save("test", memory)

        # Get the updated memory
        updated_memory = memory_repository.find("test", memory.id)

        assert updated_memory is not None
        assert len(updated_memory.learnings) == 2

        learning_ids = updated_memory.learnings
        assert learning1.id not in learning_ids  # The first learning should be removed
        assert learning2.id in learning_ids
        assert learning3.id in learning_ids

    def test_memory_without_learnings(self, memory_repository):
        """Test creating a memory without any linked learnings."""
        vec = mock_vector()
        memory = memory_repository.save(
            "test",
            Memory(
                title="Memory without Learnings",
                content="This memory has no linked learnings",
                learnings=[],
                vectors={"vector_0": vec},
            ),
        )

        retrieved_memory = memory_repository.find("test", memory.id)

        assert retrieved_memory is not None
        assert len(retrieved_memory.learnings) == 0
