from typing import List

from memiris.domain.learning import Learning
from memiris.domain.memory import Memory
from memiris.dto.memory_creation_dto import MemoryCreationDto
from memiris.dto.memory_main_dto import MemoryDto


def creation_dto_to_memory(
    memory_dto: MemoryCreationDto, learnings: List[Learning]
) -> Memory:
    """
    Convert a MemoryCreationDto to a Memory object.
    """
    return Memory(
        title=memory_dto.title,
        content=memory_dto.content,
        learnings=[
            id
            for id in memory_dto.learnings
            if id in [learning.id for learning in learnings]
        ],
    )


def memory_to_creation_dto(memory: Memory) -> MemoryCreationDto:
    """
    Convert a Memory object to a MemoryCreationDto.
    """
    return MemoryCreationDto(
        title=memory.title,
        content=memory.content,
        learnings=memory.learnings,
    )


def dto_to_memory(memory_dto: MemoryDto, learnings: List[Learning]) -> Memory:
    """
    Convert a MemoryDto to a Memory object.
    """
    return Memory(
        uid=memory_dto.id,
        title=memory_dto.title,
        content=memory_dto.content,
        learnings=[
            id
            for id in memory_dto.learnings
            if id in [learning.id for learning in learnings]
        ],
    )


def memory_to_dto(memory: Memory) -> MemoryDto:
    """
    Convert a Memory object to a MemoryDto.
    """
    return MemoryDto(
        id=memory.id,  # type: ignore
        title=memory.title,
        content=memory.content,
        learnings=memory.learnings,
    )
