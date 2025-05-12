from typing import Callable, List
from uuid import UUID

from memiris.dto.learning_main_dto import LearningDto
from memiris.repository.learning_repository import LearningRepository
from memiris.util.learning_util import learning_to_dto


def create_tool_find_similar(
    learning_repository: LearningRepository, tenant: str, vector_name: str
) -> Callable[[UUID], List[LearningDto]]:
    """
    Create a tool to find similar learnings.
    """

    def find_similar(learning_id: UUID) -> List[LearningDto]:
        """
        Find learnings that are similar to the given learning.
        Yous should call this for each learning object you want to find similar learnings for.
        This will be your main tool to use.

        Args:
            learning_id (UUID): The ID of the learning object to find similar learnings for.

        Returns:
            List[LearningDto]: A list of similar learning objects.
        """
        print(
            f"TOOL: Finding similar learnings for {learning_id} in {tenant} using {vector_name}"
        )
        learning = learning_repository.find(tenant, learning_id)

        return [
            learning_to_dto(learning)
            for learning in learning_repository.find_similar(
                tenant, vector_name, learning.vectors[vector_name], 5
            )
        ]

    return find_similar
