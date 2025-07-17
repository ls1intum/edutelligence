from typing import Callable, List

from langfuse import observe

from memiris.dto.learning_main_dto import LearningDto
from memiris.repository.learning_repository import LearningRepository
from memiris.service.vectorizer import Vectorizer
from memiris.util.learning_util import learning_to_dto
from memiris.util.uuid_util import is_valid_uuid, to_uuid


def create_tool_find_learnings_by_id(
    learning_repository: LearningRepository, tenant: str
) -> Callable[[List[str]], List[LearningDto]]:
    """
    Create a tool to find learnings by their IDs.
    """

    @observe(name="tool.learning.find_by_id")
    def find_learnings_by_id(learning_ids: List[str]) -> List[LearningDto]:
        """
        Find learnings by their IDs. Can be used to get unknown learnings of a memory.

        Args:
            learning_ids (List[UUID]): A list of learning IDs to find.

        Returns:
            List[LearningDto]: A list of learning objects that match the given IDs.
        """
        print(f"TOOL: Finding learnings by ID in {tenant}: {learning_ids}")
        return [
            learning_to_dto(learning)
            for learning_id in learning_ids
            if is_valid_uuid(learning_id)
            and (learning := learning_repository.find(tenant, to_uuid(learning_id)))  # type: ignore
            is not None
        ]

    return find_learnings_by_id


def create_tool_find_similar_learnings(
    learning_repository: LearningRepository, tenant: str
) -> Callable[[str], List[LearningDto]]:
    """
    Create a tool to find similar learnings.
    """

    @observe(name="tool.learning.find_similar")
    def find_similar_learnings(learning_id: str) -> List[LearningDto]:
        """
        Find learnings that are similar to the given learning.
        Yous should call this for each learning object you want to find similar learnings for.
        This will be your main tool to use.

        Args:
            learning_id (UUID): The ID of the learning object to find similar learnings for.

        Returns:
            List[LearningDto]: A list of similar learning objects.
        """
        if (learning_uuid := to_uuid(learning_id)) is not None:
            print(f"TOOL: Finding similar learnings for {learning_uuid} in {tenant}")
            learning = learning_repository.find(tenant, learning_uuid)

            if learning is None:
                print(f"TOOL: Learning with ID {learning_uuid} not found in {tenant}")
                return []

            return [
                learning_to_dto(learning)
                for learning in learning_repository.search_multi(
                    tenant,
                    {x: y for x, y in learning.vectors.items() if y is not None},
                    5,
                )
            ]
        else:
            print(f"TOOL: Invalid learning ID {learning_id} provided in {tenant}")
            return []

    return find_similar_learnings


def create_tool_search_learnings(
    learning_repository: LearningRepository, vectorizer: Vectorizer, tenant: str
) -> Callable[[str], List[LearningDto]]:
    """
    Create a tool to search for learnings.
    """

    @observe(name="tool.learning.search")
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
