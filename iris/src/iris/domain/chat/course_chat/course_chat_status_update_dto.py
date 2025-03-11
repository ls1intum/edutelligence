from typing import List, Optional

from src.iris.domain.status.status_update_dto import StatusUpdateDTO


class CourseChatStatusUpdateDTO(StatusUpdateDTO):
    result: Optional[str] = None
    suggestions: List[str] = []
