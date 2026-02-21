from typing import List, Optional

from iris.domain.data.verdict_dto import VerdictDTO
from iris.domain.status.status_update_dto import StatusUpdateDTO


class PromptUserChatStatusUpdateDTO(StatusUpdateDTO):
    result: Optional[str] = None
    verdict: Optional[VerdictDTO] = None
