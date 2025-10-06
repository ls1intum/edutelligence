from typing import List

from pydantic import BaseModel

from memiris.api.learning_dto import LearningDTO
from memiris.api.memory_connection_dto import MemoryConnectionDTO
from memiris.api.memory_dto import MemoryDTO


class MemoryWithRelationsDTO(BaseModel):
    """
    Combined DTO representing a Memory with its learnings and connections fully fetched.
    """

    memory: MemoryDTO
    learnings: List[LearningDTO]
    connections: List[MemoryConnectionDTO]
