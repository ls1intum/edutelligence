from abc import ABC, abstractmethod
from typing import List
from uuid import UUID

from memiris.domain.memory_connection import MemoryConnection
from memiris.repository.crud_repository import BaseRepository


class MemoryConnectionRepository(BaseRepository[MemoryConnection, UUID], ABC):
    """
    MemoryConnectionRepository is an abstract class that defines the database operations for MemoryConnection objects.
    """

    @abstractmethod
    def find_by_connection_type(
        self, tenant: str, connection_type: str
    ) -> List[MemoryConnection]:
        """
        Find all memory connections of a specific type.

        Args:
            tenant: The tenant identifier
            connection_type: Type of connection to filter by

        Returns:
            List of MemoryConnection objects of the specified type
        """
        pass
