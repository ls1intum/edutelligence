from typing import List, Optional

from pydantic import Field

from iris.domain.citation import CitationDTO
from iris.domain.status.status_update_dto import StatusUpdateDTO


class ExerciseChatStatusUpdateDTO(StatusUpdateDTO):
    result: Optional[str] = None
    session_title: Optional[str] = Field(alias="sessionTitle", default=None)
    suggestions: List[str] = []
    citations: List[CitationDTO] = []
