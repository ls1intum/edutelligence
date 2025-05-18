from typing import Callable, List
from uuid import UUID

from memiris.dto.learning_main_dto import LearningDto
from memiris.repository.learning_repository import LearningRepository
from memiris.service.vectorizer import Vectorizer
from memiris.util.learning_util import learning_to_dto


def create_tool_find_learnings_by_id(
    learning_repository: LearningRepository, tenant: str
) -> Callable[[List[UUID]], List[LearningDto]]:
    """
    Create a tool to find learnings by their IDs.
    """

    def find_learnings_by_id(learning_ids: List[UUID]) -> List[LearningDto]:
        """
        Find learnings by their IDs. Can be used to get unknown learnings of a memory.

        Args:
            learning_ids (List[UUID]): A list of learning IDs to find.

        Returns:
            List[LearningDto]: A list of learning objects that match the given IDs.
        """
        print(f"TOOL: Finding learnings by ID in {tenant}: {learning_ids}")
        return [
            learning_to_dto(learning_repository.find(tenant, learning_id))
            for learning_id in learning_ids
        ]

    return find_learnings_by_id


def create_tool_find_similar_learnings(
    learning_repository: LearningRepository, tenant: str
) -> Callable[[UUID], List[LearningDto]]:
    """
    Create a tool to find similar learnings.
    """

    def find_similar_learnings(learning_id: UUID) -> List[LearningDto]:
        """
        Find learnings that are similar to the given learning.
        Yous should call this for each learning object you want to find similar learnings for.
        This will be your main tool to use.

        Args:
            learning_id (UUID): The ID of the learning object to find similar learnings for.

        Returns:
            List[LearningDto]: A list of similar learning objects.
        """
        print(f"TOOL: Finding similar learnings for {learning_id} in {tenant}")
        learning = learning_repository.find(tenant, learning_id)

        return [
            learning_to_dto(learning)
            for learning in learning_repository.search_multi(
                tenant,
                {x: y for x, y in learning.vectors.items() if y is not None},
                5,
            )
        ]

    return find_similar_learnings


def create_tool_search_learnings(
    learning_repository: LearningRepository, vectorizer: Vectorizer, tenant: str
) -> Callable[[str], List[LearningDto]]:
    """
    Create a tool to search for learnings.
    """

    def search_learnings(query: str) -> List[LearningDto]:
        """
        Search for learnings based on the given query.

        Args:
            query (str): The search query.

        Returns:
            List[LearningDto]: A list of learning objects that match the search query.
        """
        print(f"TOOL: Searching for learnings in {tenant} with query: {query}")
        return [
            learning_to_dto(learning)
            for learning in learning_repository.search_multi(
                tenant,
                vectorizer.vectorize(query),
                10,
            )
        ]

    return search_learnings
