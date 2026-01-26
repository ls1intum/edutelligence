from typing import List, Optional

from pydantic import BaseModel

from memiris.api.learning_dto import LearningDTO
from memiris.api.memory_connection_dto import MemoryConnectionDTO
from memiris.api.memory_dto import MemoryDTO


class MemoryDataDTO(BaseModel):
    """
    A data transfer object (DTO) for representing a memory.
    See the `Memory` class for more details on the memory object.
    Excludes the vectors, as they are internal to the system.
    """

    memories: List[MemoryDTO]
    learnings: List[LearningDTO]
    connections: List[MemoryConnectionDTO]

    def __init__(
        self,
        memories: Optional[List[MemoryDTO]] = None,
        learnings: Optional[List[LearningDTO]] = None,
        connections: Optional[List[MemoryConnectionDTO]] = None,
        **data,
    ):
        super().__init__(
            memories=memories if memories is not None else [],
            learnings=learnings if learnings is not None else [],
            connections=connections if connections is not None else [],
            **data,
        )

    def __str__(self) -> str:
        return f"Memories: {len(self.memories)}, Learnings: {len(self.learnings)}, Connections: {len(self.connections)}"

    def __repr__(self) -> str:
        return (
            f"MemoryDataDTO(Memories: {len(self.memories)}, Learnings: {len(self.learnings)}, "
            f"Connections: {len(self.connections)})"
        )

    def __eq__(self, other) -> bool:
        if other is None or not isinstance(other, MemoryDataDTO):
            return False
        return (
            self.memories == other.memories
            and self.learnings == other.learnings
            and self.connections == other.connections
        )
