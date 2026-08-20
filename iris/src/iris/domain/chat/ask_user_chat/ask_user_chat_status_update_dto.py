from typing import Optional

from iris.domain.data.verdict_dto import VerdictDTO
from iris.domain.status.status_update_dto import StatusUpdateDTO


class AskUserChatStatusUpdateDTO(StatusUpdateDTO):
    """
    This DTO is sent back to Artemis with the generated question or the assessment verdict.
    - result: The generated question or feedback message.
    - verdict: The assessment verdict for the student's last answer, if one was made.
    - event: The event that triggered this update, passed back to the client.
    """

    result: Optional[str] = None
    verdict: Optional[VerdictDTO] = None
    event: Optional[str] = None
