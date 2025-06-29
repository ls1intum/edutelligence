from typing import List

from iris.domain.status.status_update_dto import StatusUpdateDTO


class RewritingStatusUpdateDTO(StatusUpdateDTO):
    result: str = ""
    suggestions: List[str] = []
    inconsistencies: List[str] = []
    improvement: str = ""
