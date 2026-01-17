from typing import List, Optional

from memiris import MemoryDTO
from pydantic import Field

from iris.domain.citation import CitationDTO
from iris.domain.status.status_update_dto import StatusUpdateDTO


class CourseChatStatusUpdateDTO(StatusUpdateDTO):
    result: Optional[str] = None
    suggestions: List[str] = []
    session_title: Optional[str] = Field(alias="sessionTitle", default=None)
    accessed_memories: List[MemoryDTO] = Field(alias="accessedMemories", default=[])
    created_memories: List[MemoryDTO] = Field(alias="createdMemories", default=[])
    citations: List[CitationDTO] = []
