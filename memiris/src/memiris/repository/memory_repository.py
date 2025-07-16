from abc import ABC, abstractmethod
from typing import List, Mapping, Sequence
from uuid import UUID

from memiris.domain.memory import Memory
from memiris.repository.crud_repository import BaseRepository


class MemoryRepository(BaseRepository[Memory, UUID], ABC):
    """
    MemoryRepository is an abstract class that defines the database operations for memory objects.
    """

    @abstractmethod
    def all(self, tenant: str, include_deleted: bool = False) -> List[Memory]:
        """
        Retrieve all entities for a given tenant.
        """
        pass

    @abstractmethod
    def search(
        self, tenant: str, vector_name: str, vector: Sequence[float], count: int
    ) -> List[Memory]:
        pass

    @abstractmethod
    def search_multi(
        self, tenant: str, vectors: Mapping[str, Sequence[float]], count: int
    ) -> List[Memory]:
        pass

    @abstractmethod
    def find_unslept_memories(self, tenant: str) -> List[Memory]:
        """
        Find all unslept memories for a given tenant.
        """
        pass
