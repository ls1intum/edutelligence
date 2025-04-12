from typing import Optional

from iris.domain.status.status_update_dto import StatusUpdateDTO


class TutorSuggestionStatusUpdateDTO(StatusUpdateDTO):
    result: Optional[str] = None
