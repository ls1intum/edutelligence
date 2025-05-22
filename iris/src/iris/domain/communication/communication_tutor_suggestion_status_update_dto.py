from typing import Optional

from iris.domain.status.status_update_dto import StatusUpdateDTO


class TutorSuggestionStatusUpdateDTO(StatusUpdateDTO):
    """
    This class is used to update the status of a tutor suggestion.
    It inherits from StatusUpdateDTO and adds two optional fields:
    - artifact: The suggestion generated.
    - result: Generated chat answer.
    """

    artifact: Optional[str] = None
    result: Optional[str] = None
