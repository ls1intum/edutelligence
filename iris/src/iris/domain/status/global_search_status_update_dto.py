from typing import List, Optional

from pydantic import Field

from iris.domain.search.lecture_search_dto import GlobalSearchSourceDTO, HandoffDTO
from iris.domain.status.status_update_dto import StatusUpdateDTO


class GlobalSearchStatusUpdateDTO(StatusUpdateDTO):
    """Status update DTO for the global search pipeline.

    Sent to Artemis via webhook at two points:
      1. Immediately after intent classification — answer=None, sources=[] (thinking)
      2. After the pipeline finishes — answer=str|None, sources=[...], handoff=HandoffDTO|None
    """

    result: Optional[str] = None
    answer: Optional[str] = None
    sources: List[GlobalSearchSourceDTO] = Field(default_factory=list)
    handoff: Optional[HandoffDTO] = None
