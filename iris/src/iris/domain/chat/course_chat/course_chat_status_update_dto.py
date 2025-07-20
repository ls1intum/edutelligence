from typing import List, Optional

from memiris import Memory

from iris.domain.status.status_update_dto import StatusUpdateDTO


class CourseChatStatusUpdateDTO(StatusUpdateDTO):
    result: Optional[str] = None
    suggestions: List[str] = []
    accessed_memories: List[Memory] = []
    created_memories: List[Memory] = []
