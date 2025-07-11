import pytest
from memiris_tests.test_utils import mock_vector
from memiris_tests.weaviate_tests.test_setup import WeaviateTest

from memiris.domain.memory import Memory
from memiris.domain.memory_connection import ConnectionType, MemoryConnection
from memiris.repository.weaviate.weaviate_memory_connection_repository import (
    WeaviateMemoryConnectionRepository,
)
from memiris.repository.weaviate.weaviate_memory_repository import (
    WeaviateMemoryRepository,
)


class TestWeaviateMemoryConnectionRepository(WeaviateTest):
    """
    TestWeaviateMemoryConnectionRepository is a test class for WeaviateMemoryConnectionRepository.
    It uses testcontainers to run a Weaviate instance in a Docker container.
    """

    @pytest.fixture
    def memory_repository(self, weaviate_client):
        return WeaviateMemoryRepository(weaviate_client)

    @pytest.fixture
    def memory_connection_repository(self, weaviate_client):
        return WeaviateMemoryConnectionRepository(weaviate_client)

    def _create_test_memory(self, memory_repository) -> Memory:
        """Helper method to create a test memory object."""
        vec = mock_vector()
        memory = memory_repository.save(
            "test",
            Memory(
                title="Test Memory Title",
                content="Test Memory Content",
                learnings=[],  # Empty list of learning UUIDs
                vectors={"vector_0": vec},
            ),
        )
        return memory

    def _create_test_connection(
        self, memory_repository, memory_connection_repository
    ) -> MemoryConnection:
        return memory_connection_repository.save(
            "test",
            MemoryConnection(
                connection_type=ConnectionType.RELATED,
                description="Memory 1 happened before Memory 2",
                weight=0.95,
                memories=[
                    self._create_test_memory(memory_repository).id,  # type: ignore
                    self._create_test_memory(memory_repository).id,  # type: ignore
                ],
            ),
        )

    def test_create(self, memory_repository, memory_connection_repository):
        """Test creating a memory connection with linked memories."""
        memory1 = self._create_test_memory(memory_repository)
        memory2 = self._create_test_memory(memory_repository)

        memory_connection = memory_connection_repository.save(
            "test",
            MemoryConnection(
                connection_type=ConnectionType.RELATED,
                description="Memory 1 happened before Memory 2",
                weight=0.95,
                memories=[memory1.id, memory2.id],
            ),
        )

        assert memory_connection is not None
        assert memory_connection.id is not None

    def test_delete(self, memory_repository, memory_connection_repository):
        """Test deleting a memory connection."""
        memory_connection = self._create_test_connection(
            memory_repository, memory_connection_repository
        )

        memory_connection_repository.delete("test", memory_connection.id)

        assert memory_connection_repository.find("test", memory_connection.id) is None

    def test_get(self, memory_repository, memory_connection_repository):
        """Test retrieving a memory connection."""
        memory_connection = self._create_test_connection(
            memory_repository, memory_connection_repository
        )

        retrieved_connection = memory_connection_repository.find(
            "test", memory_connection.id
        )

        assert retrieved_connection is not None
        assert retrieved_connection.id == memory_connection.id
        assert retrieved_connection.connection_type == memory_connection.connection_type
        assert retrieved_connection.description == memory_connection.description
        assert retrieved_connection.weight == memory_connection.weight
        assert len(retrieved_connection.memories) == 2
        assert set(memory_connection.memories) == set(retrieved_connection.memories)

    def test_update(self, memory_repository, memory_connection_repository):
        """Test updating a memory connection."""
        memory_connection = self._create_test_connection(
            memory_repository, memory_connection_repository
        )

        # Create another memory to add to the connection
        additional_memory = self._create_test_memory(memory_repository)

        memory_connection.description = "Updated Description"
        memory_connection.weight = 0.80
        memory_connection.connection_type = ConnectionType.RELATED
        memory_connection.memories.append(additional_memory.id)

        memory_connection_repository.save("test", memory_connection)

        updated_connection = memory_connection_repository.find(
            "test", memory_connection.id
        )

        assert updated_connection is not None
        assert updated_connection.id == memory_connection.id
        assert updated_connection.description == "Updated Description"
        assert updated_connection.weight == 0.80
        assert updated_connection.connection_type == ConnectionType.RELATED
        assert len(updated_connection.memories) == 3
        assert set(memory_connection.memories) == set(updated_connection.memories)

    def test_all(self, memory_repository, memory_connection_repository):
        """Test retrieving all memory connections."""
        connection1 = self._create_test_connection(
            memory_repository, memory_connection_repository
        )
        connection2 = self._create_test_connection(
            memory_repository, memory_connection_repository
        )
        connection3 = self._create_test_connection(
            memory_repository, memory_connection_repository
        )

        all_connections = memory_connection_repository.all("test")

        assert all_connections is not None
        assert len(all_connections) >= 3

        all_ids = [connection.id for connection in all_connections]

        assert connection1.id in all_ids
        assert connection2.id in all_ids
        assert connection3.id in all_ids

    def test_find_by_connection_type(
        self, memory_repository, memory_connection_repository
    ):
        """Test finding connections by connection type."""
        # Create memories
        memory1 = self._create_test_memory(memory_repository)
        memory2 = self._create_test_memory(memory_repository)
        memory3 = self._create_test_memory(memory_repository)
        memory4 = self._create_test_memory(memory_repository)

        # Create connections of different types
        connection1 = memory_connection_repository.save(
            "test",
            MemoryConnection(
                connection_type=ConnectionType.RELATED,
                description="Memory 1 and 2 sequential",
                weight=0.9,
                memories=[memory1.id, memory2.id],
            ),
        )

        connection2 = memory_connection_repository.save(
            "test",
            MemoryConnection(
                connection_type=ConnectionType.RELATED,
                description="Memory 3 caused Memory 4",
                weight=0.85,
                memories=[memory3.id, memory4.id],
            ),
        )

        connection3 = memory_connection_repository.save(
            "test",
            MemoryConnection(
                connection_type=ConnectionType.RELATED,
                description="Memory 1 caused Memory 3",
                weight=0.75,
                memories=[memory1.id, memory3.id],
            ),
        )

        # Find RELATED connections
        precedes_connections = memory_connection_repository.find_by_connection_type(
            "test", ConnectionType.RELATED.value
        )
        assert len(precedes_connections) >= 1
        assert connection1.id in [c.id for c in precedes_connections]

        # Find RELATED connections
        causes_connections = memory_connection_repository.find_by_connection_type(
            "test", ConnectionType.RELATED.value
        )
        assert len(causes_connections) >= 2
        causes_ids = [c.id for c in causes_connections]
        assert connection2.id in causes_ids
        assert connection3.id in causes_ids

        # Test with invalid connection type
        with pytest.raises(ValueError):
            memory_connection_repository.find_by_connection_type("test", "INVALID_TYPE")

    def test_bidirectional_reference_integrity(
        self, memory_repository, memory_connection_repository
    ):
        """Test that bidirectional references are maintained between memories and connections."""
        # Create memories
        memory1 = self._create_test_memory(memory_repository)
        memory2 = self._create_test_memory(memory_repository)

        # Create a connection between them
        connection = memory_connection_repository.save(
            "test",
            MemoryConnection(
                connection_type=ConnectionType.RELATED,
                description="Memory 1 happened before Memory 2",
                weight=0.95,
                memories=[memory1.id, memory2.id],
            ),
        )

        # Verify the connection has references to the memories
        retrieved_connection = memory_connection_repository.find("test", connection.id)
        assert len(retrieved_connection.memories) == 2
        assert memory1.id in retrieved_connection.memories
        assert memory2.id in retrieved_connection.memories

        # Verify the memories have references to the connection
        retrieved_memory1 = memory_repository.find("test", memory1.id)
        assert len(retrieved_memory1.connections) == 1
        assert retrieved_memory1.connections[0] == connection.id

        retrieved_memory2 = memory_repository.find("test", memory2.id)
        assert len(retrieved_memory2.connections) == 1
        assert retrieved_memory2.connections[0] == connection.id

        # Remove memory2 from the connection
        connection.memories = [memory1.id]
        memory_connection_repository.save("test", connection)

        # Verify the updated references
        retrieved_connection = memory_connection_repository.find("test", connection.id)
        assert len(retrieved_connection.memories) == 1
        assert memory1.id in retrieved_connection.memories
        assert memory2.id not in retrieved_connection.memories

        # Verify memory1 still has the reference but memory2 doesn't
        retrieved_memory1 = memory_repository.find("test", memory1.id)
        assert len(retrieved_memory1.connections) == 1

        retrieved_memory2 = memory_repository.find("test", memory2.id)
        assert len(retrieved_memory2.connections) == 0
