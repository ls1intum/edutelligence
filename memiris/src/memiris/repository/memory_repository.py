from abc import ABC
from uuid import UUID

from memiris.domain.memory import Memory
from memiris.repository.crud_repository import BaseRepository


class MemoryRepository(BaseRepository[Memory, UUID], ABC):
    """
    MemoryRepository is an abstract class that defines the database operations for memory objects.
    """

    pass
