from typing import List, Optional

from iris.domain.search.lecture_search_dto import LectureSearchResultDTO
from iris.domain.status.status_update_dto import StatusUpdateDTO


class GlobalSearchStatusUpdateDTO(StatusUpdateDTO):
    """Status update DTO for the global search pipeline.

    Sent to Artemis via webhook at two points:
      1. Immediately after intent classification — answer=None, sources=[] (thinking)
      2. After the pipeline finishes — answer=str|None, sources=[...]
    """

    answer: Optional[str] = None
    sources: List[LectureSearchResultDTO] = []
