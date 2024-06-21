from typing import Optional

from app.domain.status.status_update_dto import StatusUpdateDTO


class ExerciseChatStatusUpdateDTO(StatusUpdateDTO):
    result: Optional[str] = None
