from iris.domain.status.status_update_dto import StatusUpdateDTO
from typing import List


class RewritingStatusUpdateDTO(StatusUpdateDTO):
    result: str = ""
    suggestions: List[str] = []
    inconsistencies: List[str] = []
    improvement: str= ""

