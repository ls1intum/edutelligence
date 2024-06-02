from typing import Optional, List

from app.domain.status.status_update_dto import StatusUpdateDTO


class CourseChatStatusUpdateDTO(StatusUpdateDTO):
    result: Optional[str] = None
    suggestions: List[str] = []
