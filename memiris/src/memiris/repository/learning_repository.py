from abc import ABC, abstractmethod
from typing import Mapping, Sequence
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
    ) -> list[Learning]:
        pass

    @abstractmethod
    def search_multi(
        self, tenant: str, vectors: Mapping[str, Sequence[float]], count: int
    ) -> list[Learning]:
        pass

    @abstractmethod
    def find_by_ids(self, tenant: str, ids: list[UUID]) -> list[Learning]:
        """
        Retrieve multiple learning objects by their IDs in a single batch operation.

        Args:
            tenant: The tenant identifier
            ids: List of learning IDs to retrieve

        Returns:
            List of Learning objects that match the provided IDs
        """
        pass
