from typing import List, Optional

from pydantic import BaseModel, Field

from memiris.domain.memory import Memory


class MemoryDTO(BaseModel):
    """
    A data transfer object (DTO) for representing a memory.
    See the `Memory` class for more details on the memory object.
    Excludes the vectors, as they are internal to the system.
    """

    id: Optional[str]
    title: str
    content: str
    learnings: List[str]
    connections: List[str]
    slept_on: bool = Field(alias="sleptOn", default=False)
    deleted: bool = False

    @classmethod
    def from_memory(cls, memory: Memory) -> "MemoryDTO":
        """
        Create a MemoryDto from a Memory object.
        """
        return cls(
            id=str(memory.id) if memory.id else None,
            title=memory.title,
            content=memory.content,
            learnings=[str(id) for id in memory.learnings],
            connections=[str(id) for id in memory.connections],
            sleptOn=memory.slept_on,
            deleted=memory.deleted,
        )

    def __str__(self) -> str:
        return f"{self.title}: {self.content} ({self.learnings})"

    def __repr__(self) -> str:
        return (
            f"Memory({self.id}, {self.title}, {self.content}, {repr(self.learnings)})"
        )

    def __eq__(self, other) -> bool:
        if other is None or not isinstance(other, MemoryDTO):
            return False
        if self.id:
            return self.id == other.id
        return (
            self.title == other.title
            and self.content == other.content
            and self.learnings == other.learnings
            and self.connections == other.connections
            and self.slept_on == other.slept_on
            and self.deleted == other.deleted
        )
