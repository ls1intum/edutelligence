from typing import Callable, List

from langfuse import observe

from memiris.dlo.memory_main_dlo import MemoryDLO
from memiris.repository.memory_repository import MemoryRepository
from memiris.service.vectorizer import Vectorizer
from memiris.util.memory_util import memory_to_dlo
from memiris.util.uuid_util import to_uuid


def create_tool_find_similar(
    memory_repository: MemoryRepository, tenant: str
) -> Callable[[str], List[MemoryDLO]]:
    """
    Create a tool to find similar memories.
    """

    @observe(name="tool.memory.find_by_id")
    def find_similar_memories(memory_id: str) -> List[MemoryDLO]:
        """
        Find memories that are similar to the given memory.
        You should call this for each memory object you want to find similar memories for.
        This will be your main tool to use.

        Args:
            memory_id (UUID): The ID of the memory object to find similar memories for.

        Returns:
            List[MemoryDLO]: A list of similar memory objects.
        """
        if (memory_uuid := to_uuid(memory_id)) is not None:
            print(f"TOOL: Finding similar memories for {memory_uuid} in {tenant}")
            memory = memory_repository.find(tenant, memory_uuid)

            if memory is None:
                print(f"Memory with ID {memory_uuid} not found in {tenant}")
                return []

            return [
                memory_to_dlo(memory)
                for memory in memory_repository.search_multi(
                    tenant,
                    {x: y for x, y in memory.vectors.items() if y is not None},
                    5,
                )
            ]
        else:
            return []

    return find_similar_memories


def create_tool_search_memories(
    memory_repository: MemoryRepository, vectorizer: Vectorizer, tenant: str
) -> Callable[[str], List[MemoryDLO]]:
    """
    Create a tool to search for memories.
    """

    @observe(name="tool.memory.search")
    def search_memories(query: str) -> List[MemoryDLO]:
        """
        Search for memories based on the given query.

        Args:
            query (str): The search query.

        Returns:
            List[MemoryDLO]: A list of memory objects that match the search query.
        """
        print(f"TOOL: Searching for memories in {tenant} with query: {query}")
        return [
            memory_to_dlo(memory)
            for memory in memory_repository.search_multi(
                tenant,
                vectorizer.vectorize(query),
                10,
            )
        ]

    return search_memories
