import abc
from abc import ABC
from typing import Mapping, Sequence
from uuid import UUID

from memiris.domain.memory import Memory
from memiris.repository.crud_repository import BaseRepository


class MemoryRepository(BaseRepository[Memory, UUID], ABC):
    """
    MemoryRepository is an abstract class that defines the database operations for memory objects.
    """

    @abc.abstractmethod
    def search(
        self, tenant: str, vector_name: str, vector: Sequence[float], count: int
    ) -> list[Memory]:
        pass

    @abc.abstractmethod
    def search_multi(
        self, tenant: str, vectors: Mapping[str, Sequence[float]], count: int
    ) -> list[Memory]:
        pass
