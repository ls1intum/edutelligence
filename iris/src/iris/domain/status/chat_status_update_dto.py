from typing import List, Optional

from memiris.api.memory_dto import MemoryDTO
from pydantic import Field

from iris.domain.status.status_update_dto import StatusUpdateDTO


class ChatStatusUpdateDTO(StatusUpdateDTO):
    result: Optional[str] = None
    session_title: Optional[str] = Field(alias="sessionTitle", default=None)
    suggestions: List[str] = []
    accessed_memories: List[MemoryDTO] = Field(alias="accessedMemories", default=[])
    created_memories: List[MemoryDTO] = Field(alias="createdMemories", default=[])
