from typing import Callable, List
from uuid import UUID

from memiris.dto.memory_main_dto import MemoryDto
from memiris.repository.memory_repository import MemoryRepository
from memiris.service.vectorizer import Vectorizer
from memiris.util.memory_util import memory_to_dto


def create_tool_find_similar(
    memory_repository: MemoryRepository, tenant: str
) -> Callable[[UUID], List[MemoryDto]]:
    """
    Create a tool to find similar memories.
    """

    def find_similar_memories(memory_id: UUID) -> List[MemoryDto]:
        """
        Find memories that are similar to the given memory.
        Yous should call this for each memory object you want to find similar memories for.
        This will be your main tool to use.

        Args:
            memory_id (UUID): The ID of the memory object to find similar memories for.

        Returns:
            List[MemoryDto]: A list of similar memory objects.
        """
        print(f"TOOL: Finding similar memories for {memory_id} in {tenant}")
        memory = memory_repository.find(tenant, memory_id)

        return [
            memory_to_dto(memory)
            for memory in memory_repository.search_multi(
                tenant,
                {x: y for x, y in memory.vectors.items() if y is not None},
                5,
            )
        ]

    return find_similar_memories


def create_tool_search_memories(
    memory_repository: MemoryRepository, vectorizer: Vectorizer, tenant: str
) -> Callable[[str], List[MemoryDto]]:
    """
    Create a tool to search for memories.
    """

    def search_memories(query: str) -> List[MemoryDto]:
        """
        Search for memories based on the given query.

        Args:
            query (str): The search query.

        Returns:
            List[MemoryDto]: A list of memory objects that match the search query.
        """
        print(f"TOOL: Searching for memories in {tenant} with query: {query}")
        return [
            memory_to_dto(memory)
            for memory in memory_repository.search_multi(
                tenant,
                vectorizer.vectorize(query),
                10,
            )
        ]

    return search_memories
