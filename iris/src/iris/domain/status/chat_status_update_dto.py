from typing import List, Optional

from memiris.api.memory_dto import MemoryDTO
from pydantic import Field

from iris.domain.status.activity_dto import ActivityDTO
from iris.domain.status.status_update_dto import StatusUpdateDTO
from iris.domain.status.suggested_context_dto import SuggestedContextDTO


class ChatStatusUpdateDTO(StatusUpdateDTO):
    result: Optional[str] = None
    final: Optional[bool] = Field(alias="final", default=None)
    partial_result: Optional[str] = Field(alias="partialResult", default=None)
    partial_seq: Optional[int] = Field(alias="partialSeq", default=None)
    session_title: Optional[str] = Field(alias="sessionTitle", default=None)
    suggestions: Optional[List[str]] = Field(default_factory=list)
    accessed_memories: List[MemoryDTO] = Field(alias="accessedMemories", default=[])
    created_memories: List[MemoryDTO] = Field(alias="createdMemories", default=[])
    activities: Optional[List[ActivityDTO]] = None
    activity_seq: Optional[int] = Field(alias="activitySeq", default=None)
    suggested_context: Optional[SuggestedContextDTO] = Field(
        alias="suggestedContext", default=None
    )
