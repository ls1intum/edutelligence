from abc import ABC, abstractmethod
from typing import List, Mapping, Sequence
from uuid import UUID

from memiris.domain.learning import Learning
from memiris.repository.crud_repository import BaseRepository


class LearningRepository(BaseRepository[Learning, UUID], ABC):
    """
    LearningRepository is an abstract class that defines the database operations for Learning objects.
    """

    @abstractmethod
    def search(
        self, tenant: str, vector_name: str, vector: Sequence[float], count: int
    ) -> List[Learning]:
        pass

    @abstractmethod
    def search_multi(
        self, tenant: str, vectors: Mapping[str, Sequence[float]], count: int
    ) -> List[Learning]:
        pass
