from typing import List, Optional

from iris.domain.status.status_update_dto import StatusUpdateDTO


class PromptUserChatStatusUpdateDTO(StatusUpdateDTO):
    result: Optional[str] = None
    reasoning: Optional[str] = None
