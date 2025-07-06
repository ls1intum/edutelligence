from uuid import UUID

from memiris.domain.memory import Memory
from memiris.repository.memory_repository import MemoryRepository


class MemoryService:
    """
    MemoryService is a class that provides an interface for managing memory operations.
    It includes methods for adding, retrieving, and deleting memory entries.
    """

    _memory_repository: MemoryRepository

    def __init__(self, memory_repository: MemoryRepository) -> None:
        """
        Initialize the MemoryService with a MemoryRepository instance.

        Args:
            memory_repository: An instance of MemoryRepository to handle memory operations.
        """
        if not memory_repository:
            raise ValueError("MemoryRepository must be provided.")

        self._memory_repository = memory_repository

    def get_memory_by_id(self, tenant: str, memory_id: str | UUID) -> Memory:
        """
        Retrieve a memory entry by its ID.

        Args:
            tenant: The tenant to which the memory belongs.
            memory_id: The ID of the memory entry to retrieve.

        Returns:
            Memory: The memory object corresponding to the provided ID.
        """
        return self._memory_repository.find(tenant, memory_id)

    def get_all_memories(self, tenant: str) -> list[Memory]:
        """
        Retrieve all memory entries for a given tenant.

        Args:
            tenant: The tenant to which the memories belong.

        Returns:
            list[Memory]: A list of all memory objects for the specified tenant.
        """
        return self._memory_repository.all(tenant)

    def delete_memory(self, tenant: str, memory_id: str | UUID) -> None:
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
