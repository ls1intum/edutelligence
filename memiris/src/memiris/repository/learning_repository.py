import abc
from abc import ABC
from typing import Mapping, Sequence
from uuid import UUID

from memiris.domain.learning import Learning
from memiris.repository.crud_repository import BaseRepository


class LearningRepository(BaseRepository[Learning, UUID], ABC):
    """
    LearningRepository is an abstract class that defines the database operations for Learning objects.
    """

    @abc.abstractmethod
    def search(
        self, tenant: str, vector_name: str, vector: Sequence[float], count: int
    ) -> list[Learning]:
        pass

    @abc.abstractmethod
    def search_multi(
        self, tenant: str, vectors: Mapping[str, Sequence[float]], count: int
    ) -> list[Learning]:
        pass
