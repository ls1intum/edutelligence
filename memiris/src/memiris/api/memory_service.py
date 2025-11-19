from typing import Mapping, Optional, Sequence, overload
from uuid import UUID

from weaviate.client import WeaviateClient

from memiris.domain.memory import Memory
from memiris.repository.memory_repository import MemoryRepository
from memiris.repository.weaviate.weaviate_memory_repository import (
    WeaviateMemoryRepository,
)


class MemoryService:
    """
    MemoryService is a class that provides an interface for managing memory operations.
    It includes methods for adding, retrieving, and deleting memory entries.
    """

    _memory_repository: MemoryRepository

    @overload
    def __init__(self, value: MemoryRepository) -> None:
        """
        Initialize the MemoryService with a MemoryRepository instance.

        Args:
            value: An instance of MemoryRepository to handle memory operations.
        """

    @overload
    def __init__(self, value: WeaviateClient) -> None:
        """
        Initialize the MemoryService with a WeaviateClient instance.

        Args:
            value: An instance of WeaviateClient to handle memory operations.
        """

    def __init__(self, value: MemoryRepository | WeaviateClient) -> None:
        """
        Initialize the MemoryService with a MemoryRepository or WeaviateClient instance.
        Args:
            value: An instance of MemoryRepository or WeaviateClient to handle memory operations.
        """
        if isinstance(value, MemoryRepository):
            self._memory_repository = value
        elif isinstance(value, WeaviateClient):
            self._memory_repository = WeaviateMemoryRepository(value)
        else:
            raise TypeError(
                f"Expected MemoryRepository or WeaviateClient instance, got {type(value)}"
            )

    def get_memory_by_id(self, tenant: str, memory_id: UUID) -> Optional[Memory]:
        """
        Retrieve a memory entry by its ID.

        Args:
            tenant: The tenant to which the memory belongs.
            memory_id: The ID of the memory entry to retrieve.

        Returns:
            Memory: The memory object corresponding to the provided ID.
        """
        return self._memory_repository.find(tenant, memory_id)

    def get_memories_by_ids(
        self, tenant: str, memory_ids: list[UUID]
    ) -> Sequence[Memory]:
        """
        Retrieve multiple memory entries by their IDs.

        Args:
            tenant: The tenant to which the memories belong.
            memory_ids: A list of memory IDs to retrieve.

        Returns:
            list[Memory]: A list of memory objects corresponding to the provided IDs.
        """
        if not memory_ids:
            return []

        return self._memory_repository.find_by_ids(tenant, memory_ids)

    def get_all_memories(self, tenant: str) -> list[Memory]:
        """
        Retrieve all memory entries for a given tenant.

        Args:
            tenant: The tenant to which the memories belong.

        Returns:
            list[Memory]: A list of all memory objects for the specified tenant.
        """
        return self._memory_repository.all(tenant)

    def delete_memory(self, tenant: str, memory_id: UUID) -> None:
        """
        Delete a memory entry by its ID.

        Args:
            tenant: The tenant to which the memory belongs.
            memory_id: The ID of the memory entry to delete.

        Returns:
            None
        """
        self._memory_repository.delete(tenant, memory_id)

    def save_memory(self, tenant: str, memory: Memory) -> Memory:
        """
        Update a memory. Not suitable for creating new memories!

        Args:
            tenant: The tenant to which the memory belongs.
            memory: The Memory object to save.

        Returns:
            Memory: The saved memory object.
        """
        if not memory:
            raise ValueError("Memory object must be provided.")
        if not memory.id:
            raise ValueError("Memory object must have an ID.")

        return self._memory_repository.save(tenant, memory)

    def semantic_search(
        self, tenant: str, vectors: Mapping[str, Sequence[float]], limit: int = 10
    ) -> Sequence[Memory]:
        return self._memory_repository.search_multi(tenant, vectors, limit)

    def has_unslept_memories(self, tenant: str) -> bool:
        """
        Check if there are any unslept memories for a given tenant.

        Args:
            tenant: The tenant to which the memories belong.
        Returns:
            bool: True if there are unslept memories, False otherwise.
        """
        return len(self._memory_repository.find_unslept_memories(tenant)) > 0

    def find_all_tenants(self) -> list[str]:
        """
        Retrieve all tenants that have memory entries.

        Returns:
            list[str]: A list of tenant identifiers.
        """
        if isinstance(self._memory_repository, WeaviateMemoryRepository):
            return self._memory_repository.find_all_tenants()
        else:
            raise NotImplementedError(
                "find_all_tenants is only implemented for WeaviateMemoryRepository."
            )
