from typing import Optional, Sequence, overload
from uuid import UUID

from weaviate.client import WeaviateClient

from memiris.domain.memory_connection import MemoryConnection
from memiris.repository.memory_connection_repository import MemoryConnectionRepository
from memiris.repository.weaviate.weaviate_memory_connection_repository import (
    WeaviateMemoryConnectionRepository,
)


class MemoryConnectionService:
    """
    MemoryConnectionService is a class that provides an interface for managing memory_connection operations.
    It includes methods for adding, retrieving, and deleting memory_connection entries.
    """

    _memory_connection_repository: MemoryConnectionRepository

    @overload
    def __init__(self, value: MemoryConnectionRepository) -> None:
        """
        Initialize the MemoryConnectionService with a MemoryConnectionRepository instance.

        Args:
            value: An instance of MemoryConnectionRepository
            to handle memory connection operations.
        """

    @overload
    def __init__(self, value: WeaviateClient) -> None:
        """
        Initialize the MemoryConnectionService with a WeaviateClient instance.

        Args:
            value: An instance of WeaviateClient to handle memory connection operations.
        """

    def __init__(self, value: MemoryConnectionRepository | WeaviateClient) -> None:
        """
        Initialize the MemoryConnectionService with a MemoryConnectionRepository or WeaviateClient instance.
        Args:
            value: An instance of MemoryConnectionRepository or WeaviateClient to handle memory connection operations.
        """
        if isinstance(value, MemoryConnectionRepository):
            self._memory_connection_repository = value
        elif isinstance(value, WeaviateClient):
            self._memory_connection_repository = WeaviateMemoryConnectionRepository(
                value
            )
        else:
            raise TypeError(
                f"Expected MemoryConnectionRepository or WeaviateClient instance, got {type(value)}"
            )

    def get_memory_connection_by_id(
        self, tenant: str, memory_connection_id: UUID
    ) -> Optional[MemoryConnection]:
        """
        Retrieve a memory connection entry by its ID.

        Args:
            tenant: The tenant to which the memory connection belongs.
            memory_connection_id: The ID of the memory connection entry to retrieve.

        Returns:
            MemoryConnection: The memory connection object corresponding to the provided ID.
        """
        return self._memory_connection_repository.find(tenant, memory_connection_id)

    def get_memory_connections_by_ids(
        self, tenant: str, memory_connection_ids: list[UUID]
    ) -> Sequence[MemoryConnection]:
        """
        Retrieve multiple memory connection entries by their IDs.

        Args:
            tenant: The tenant to which the memory connections belong.
            memory_connection_ids: A list of memory connection IDs to retrieve.

        Returns:
            list[MemoryConnection]: A list of memory connection objects corresponding to the provided IDs.
        """
        if not memory_connection_ids:
            return []

        return self._memory_connection_repository.find_by_ids(
            tenant, memory_connection_ids
        )

    def get_all_memory_connections(self, tenant: str) -> list[MemoryConnection]:
        """
        Retrieve all memory connection entries for a given tenant.

        Args:
            tenant: The tenant to which the memoryconnections belong.

        Returns:
            list[MemoryConnection]: A list of all memory connection objects for the specified tenant.
        """
        return self._memory_connection_repository.all(tenant)

    def delete_memory_connection(self, tenant: str, memory_connection_id: UUID) -> None:
        """
        Delete a memory connection entry by its ID.

        Args:
            tenant: The tenant to which the memory connection belongs.
            memory_connection_id: The ID of the memory connection entry to delete.

        Returns:
            None
        """
        self._memory_connection_repository.delete(tenant, memory_connection_id)

    def save_memory_connection(
        self, tenant: str, memory_connection: MemoryConnection
    ) -> MemoryConnection:
        """
        Update a memory connection. Not suitable for creating new memory connections!

        Args:
            tenant: The tenant to which the memory connection belongs.
            memory_connection: The MemoryConnection object to save.

        Returns:
            MemoryConnection: The saved memory connection object.
        """
        if not memory_connection:
            raise ValueError("MemoryConnection object must be provided.")
        if not memory_connection.id:
            raise ValueError("MemoryConnection object must have an ID.")

        return self._memory_connection_repository.save(tenant, memory_connection)
