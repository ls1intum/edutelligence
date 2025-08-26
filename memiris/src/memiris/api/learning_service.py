from typing import Optional, Sequence, overload
from uuid import UUID

from weaviate.client import WeaviateClient

from memiris.domain.learning import Learning
from memiris.repository.learning_repository import LearningRepository
from memiris.repository.weaviate.weaviate_learning_repository import (
    WeaviateLearningRepository,
)


class LearningService:
    """
    LearningService is a class that provides an interface for managing learning operations.
    It includes methods for adding, retrieving, and deleting learning entries.
    """

    _learning_repository: LearningRepository

    @overload
    def __init__(self, value: LearningRepository) -> None:
        """
        Initialize the LearningService with a LearningRepository instance.

        Args:
            value: An instance of LearningRepository to handle learning operations.
        """

    @overload
    def __init__(self, value: WeaviateClient) -> None:
        """
        Initialize the LearningService with a WeaviateClient instance.

        Args:
            value: An instance of WeaviateClient to handle learning operations.
        """

    def __init__(self, value: LearningRepository | WeaviateClient) -> None:
        """
        Initialize the LearningService with a LearningRepository or WeaviateClient instance.
        Args:
            value: An instance of LearningRepository or WeaviateClient to handle learning operations.
        """
        if isinstance(value, LearningRepository):
            self._learning_repository = value
        elif isinstance(value, WeaviateClient):
            self._learning_repository = WeaviateLearningRepository(value)
        else:
            raise TypeError(
                f"Expected LearningRepository or WeaviateClient instance, got {type(value)}"
            )

    def get_learning_by_id(self, tenant: str, learning_id: UUID) -> Optional[Learning]:
        """
        Retrieve a learning entry by its ID.

        Args:
            tenant: The tenant to which the learning belongs.
            learning_id: The ID of the learning entry to retrieve.

        Returns:
            Learning: The learning object corresponding to the provided ID.
        """
        return self._learning_repository.find(tenant, learning_id)

    def get_learnings_by_ids(
        self, tenant: str, learning_ids: list[UUID]
    ) -> Sequence[Learning]:
        """
        Retrieve multiple learning entries by their IDs.

        Args:
            tenant: The tenant to which the learnings belong.
            learning_ids: A list of learning IDs to retrieve.

        Returns:
            list[Learning]: A list of learning objects corresponding to the provided IDs.
        """
        if not learning_ids:
            return []

        return self._learning_repository.find_by_ids(tenant, learning_ids)

    def get_all_learnings(self, tenant: str) -> list[Learning]:
        """
        Retrieve all learning entries for a given tenant.

        Args:
            tenant: The tenant to which the learnings belong.

        Returns:
            list[Learning]: A list of all learning objects for the specified tenant.
        """
        return self._learning_repository.all(tenant)

    def delete_learning(self, tenant: str, learning_id: UUID) -> None:
        """
        Delete a learning entry by its ID.

        Args:
            tenant: The tenant to which the learning belongs.
            learning_id: The ID of the learning entry to delete.

        Returns:
            None
        """
        self._learning_repository.delete(tenant, learning_id)

    def save_learning(self, tenant: str, learning: Learning) -> Learning:
        """
        Update a learning. Not suitable for creating new learnings!

        Args:
            tenant: The tenant to which the learning belongs.
            learning: The Learning object to save.

        Returns:
            Learning: The saved learning object.
        """
        if not learning:
            raise ValueError("Learning object must be provided.")
        if not learning.id:
            raise ValueError("Learning object must have an ID.")

        return self._learning_repository.save(tenant, learning)
