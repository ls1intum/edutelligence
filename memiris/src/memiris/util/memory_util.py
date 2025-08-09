from typing import List

from memiris.dlo.memory_creation_dlo import MemoryCreationDLO
from memiris.dlo.memory_main_dlo import MemoryDLO
from memiris.domain.learning import Learning
from memiris.domain.memory import Memory


def creation_dlo_to_memory(
    memory_dlo: MemoryCreationDLO, learnings: List[Learning]
) -> Memory:
    """
    Convert a MemoryCreationDLO to a Memory object.
    """
    return Memory(
        title=memory_dlo.title,
        content=memory_dlo.content,
        learnings=[
            id
            for id in memory_dlo.learnings
            if id in [learning.id for learning in learnings]
        ],
    )


def memory_to_creation_dlo(memory: Memory) -> MemoryCreationDLO:
    """
    Convert a Memory object to a MemoryCreationDLO.
    """
    return MemoryCreationDLO(
        title=memory.title,
        content=memory.content,
        learnings=memory.learnings,
    )


def dlo_to_memory(memory_dlo: MemoryDLO, learnings: List[Learning]) -> Memory:
    """
    Convert a MemoryDLO to a Memory object.
    """
    return Memory(
        uid=memory_dlo.id,
        title=memory_dlo.title,
        content=memory_dlo.content,
        learnings=[
            id
            for id in memory_dlo.learnings
            if id in [learning.id for learning in learnings]
        ],
    )


def memory_to_dlo(memory: Memory) -> MemoryDLO:
    """
    Convert a Memory object to a MemoryDLO.
    """
    return MemoryDLO(
        id=memory.id,  # type: ignore
        title=memory.title,
        content=memory.content,
        learnings=memory.learnings,
    )
